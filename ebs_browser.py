#!/usr/bin/env python3
"""EBS-Browser — navegador dedicado ao Oracle E-Business Suite.

Regras:
  - So abre UMA instancia EBS, validada antes de carregar qualquer pagina.
  - Tudo fora dessa instancia e bloqueado na camada de REDE (nem imagem, nem script).
  - Renderiza o OAF (web) com engine Chromium.
  - Forms (Java Web Start): quando o EBS devolve o JNLP, salva os bytes JA BAIXADOS e entrega
    o ARQUIVO ao OpenWebStart. Nunca re-busca a URL: o EBS rotaciona o ticket `fsst` a cada
    requisicao valida, e re-buscar usa um ticket consumido -> o servidor devolve HTML de erro.
"""
import json, os, re, subprocess, sys, tempfile, threading, time, urllib.request
from urllib.parse import urlparse

from PySide6.QtCore import QUrl, QBuffer, QIODevice, QObject, Signal, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QToolBar, QLabel, QLineEdit, QMessageBox,
                               QSizePolicy, QTabWidget)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineDownloadRequest,
                                     QWebEngineUrlRequestInterceptor, QWebEngineSettings,
                                     QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)

APP      = "EBS-Browser"
CFG_DIR  = os.path.expanduser("~/Library/Application Support/EBS-Browser")
CFG      = os.path.join(CFG_DIR, "config.json")
OWS_APP  = "/Applications/OpenWebStart/OpenWebStart javaws.app"
OWS_STUB = OWS_APP + "/Contents/MacOS/JavaApplicationStub"
# Runtime JWS EMBUTIDO no bundle: JRE 8 + motor IcedTea-Web (openwebstart.jar). Sem OpenWebStart
# externo. O launcher do .app exporta EBS_BUNDLE; rodando pelo run.sh cai no /Applications.
BUNDLE   = os.environ.get("EBS_BUNDLE") or "/Applications/EBS-Browser.app"
JWS_DIR  = os.path.join(BUNDLE, "Contents", "Resources", "jws")
JWS_JAVA = os.path.join(JWS_DIR, "jre", "bin", "java")
JWS_JAR  = os.path.join(JWS_DIR, "openwebstart.jar")
ICON_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon-1024.png")
DEFAULT_EBS = "http://apps.example.com:8000"
# O launcher de Forms do EBS escolhe JWS (JNLP) pelo User-Agent. Com o UA do QtWebEngine ele
# cai no modo applet (pagina HTML so com o copyright). Com UA de Firefox, gera o JNLP.
FIREFOX_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0"

LOG_FILE = os.path.expanduser("~/Library/Logs/EBS-Browser.log")

def log(*a):
    """stdout E arquivo: o log tem que existir seja qual for a forma de lancamento (.app/open/run.sh)."""
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    # Lancado pelo .app, o stdout JA e o arquivo de log (redirecionado pelo launcher):
    # gravar de novo duplicava cada linha. So grava no arquivo quando stdout e um terminal.
    if not sys.stdout.isatty():
        return
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_cfg():
    try:
        return json.load(open(CFG))
    except Exception:
        return {"ebs_url": DEFAULT_EBS}


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    json.dump(c, open(CFG, "w"), indent=2)


def origin_of(url):
    p = urlparse(url if "://" in url else "http://" + url)
    port = p.port or (443 if p.scheme == "https" else 80)
    return (p.scheme, (p.hostname or "").lower(), port)


def base_of(url):
    s, h, p = origin_of(url)
    return f"{s}://{h}:{p}"


def qurl_origin(u):
    port = u.port() if u.port() != -1 else (443 if u.scheme() == "https" else 80)
    return (u.scheme(), u.host().lower(), port)


def is_ebs_instance(base):
    """Prova que e EBS DE VERDADE antes de abrir qualquer coisa."""
    probes = ["/forms/frmservlet", "/OA_HTML/AppsLogin", "/OA_HTML/AppsLocalLogin.jsp"]
    for path in probes:
        try:
            req = urllib.request.Request(base + path, headers={"User-Agent": APP})
            with urllib.request.urlopen(req, timeout=6) as r:
                ct = (r.headers.get("Content-Type") or "").lower()
                body = r.read(8000).decode("latin-1", "replace")
                if "x-java-jnlp-file" in ct:                       # assinatura inequivoca do Forms EBS
                    return True
                if re.search(r"E-Business Suite|Oracle Applications|AppsLocalLogin|/OA_HTML/", body, re.I):
                    return True
        except Exception:
            continue
    return False


def _normalize_jnlp(data):
    """O EBS escreve o JNLP com entidades NUMERICAS (&#38; &#39; ...). O parser XML do
    IcedTea-Web (openwebstart.jar) NAO as decodifica: o applet recebe '&#38;' literal dentro do
    serverURL, o cliente Forms ve o '#' e morre com "MalformedURLException: Illegal character
    in URL" logo apos abrir o frame. O Java Web Start da Oracle decodifica — por isso la funciona.
    Normalizamos para entidades nomeadas/literais, que o IcedTea entende. Comprovado: com isso
    a janela "Oracle Developer Forms Runtime - Web" abre e a JVM fica viva."""
    for k, v in ((b"&#38;", b"&amp;"), (b"&#39;", b"'"), (b"&#34;", b"&quot;"),
                 (b"&#60;", b"&lt;"), (b"&#62;", b"&gt;")):
        data = data.replace(k, v)
    def _sub(m):
        n = int(m.group(1))
        if n in (34, 38, 60, 62):
            return m.group(0)
        try:
            return chr(n).encode("utf-8")
        except Exception:
            return m.group(0)
    return re.sub(rb"&#(\d+);", _sub, data)


class OnlyEbs(QWebEngineUrlRequestInterceptor):
    """Bloqueia na REDE qualquer requisicao fora da instancia EBS ATUAL da janela —
    trocar de instancia pela barra de endereco vale na hora, sem recriar nada."""
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def interceptRequest(self, info):
        u = info.requestUrl()
        us = u.toString()
        if any(k in us for k in ("frmservlet", ".jnlp", "runforms")):
            log("req", info.resourceType(), info.navigationType(), us[:170])
        if u.scheme() in ("data", "blob", "about", "qrc", "jnlp", "jnlps"):
            return
        if qurl_origin(u) != self.win.origin:
            log("req BLOCK", us[:150])
            info.block(True)


class JnlpScheme(QWebEngineUrlSchemeHandler):
    """runforms.jsp no macOS faz window.location = jnlp://host:porta/forms/frmservlet?...
    (protocolo do Java Web Start). Entregar essa URL ao OpenWebStart faz ele busca-la DUAS
    vezes (leitura + update check) e a 2a usa o ticket fsst ja rotacionado -> HTML de erro.
    Aqui buscamos UMA vez, salvamos e entregamos o ARQUIVO: sem href, nada e re-buscado."""
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def requestStarted(self, job):
        self.win.launch_jnlp_url(job.requestUrl())
        buf = QBuffer(job)
        buf.setData(b"<html><body style='font-family:sans-serif;padding:2em'>"
                    b"<h3>Forms entregue ao OpenWebStart.</h3>"
                    b"<p>Se a janela do Forms nao abrir em alguns segundos, veja o log em "
                    b"~/Library/Logs/EBS-Browser.log</p></body></html>")
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(b"text/html", buf)


class EbsPage(QWebEnginePage):
    def __init__(self, profile, win):
        super().__init__(profile, win)
        self.win = win

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ("jnlp", "jnlps"):
            log("nav jnlp:", url.toString()[:170])
            self.win.launch_jnlp_url(url, page=self)
            return False
        ok = qurl_origin(url) == self.win.origin
        log("nav", "main" if is_main_frame else "sub ", "OK   " if ok else "BLOCK", url.toString()[:170])
        if ok:
            return True
        if is_main_frame:
            self.win.status(f"bloqueado: {url.host()} nao e a instancia EBS")
        return False

    def createWindow(self, _type):
        # window.open() do EBS (launcher do Forms, LOVs, ajuda) -> ABA NOVA, mesma politica.
        # Antes devolvia self e o launcher engolia a Home.
        log("popup -> aba nova")
        return self.win.new_tab().page()


class _Validator(QObject):
    """Emitido da thread de validacao; o Qt o enfileira para a thread da janela."""
    done = Signal(str, str, bool)


class Browser(QMainWindow):
    def __init__(self, ebs_base):
        super().__init__()
        self.ebs_base = ebs_base
        self.origin = origin_of(ebs_base)
        self.resize(1400, 900)

        os.makedirs(CFG_DIR, exist_ok=True)
        self.profile = QWebEngineProfile("ebs", self)          # nomeado = persistente (login sobrevive)
        self.profile.setPersistentStoragePath(os.path.join(CFG_DIR, "profile"))
        self.profile.setCachePath(os.path.join(CFG_DIR, "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.interceptor = OnlyEbs(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(self.on_download)
        self.jnlp_handler = JnlpScheme(self)
        for sch in (b"jnlp", b"jnlps"):
            self.profile.installUrlSchemeHandler(sch, self.jnlp_handler)
        self.profile.setHttpUserAgent(FIREFOX_UA)
        log("UA:", self.profile.httpUserAgent())

        # ABAS: a Home e a aba 0 e NUNCA fecha. Popups/Forms abrem em abas novas; a aba do
        # launcher do Forms se fecha sozinha depois que o JNLP e entregue ao Java.
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        for text, slot in (("◀", lambda: self.cur().back()), ("▶", lambda: self.cur().forward()),
                           ("⟳", lambda: self.cur().reload()), ("⌂", self.home)):
            a = QAction(text, self)
            a.triggered.connect(slot)
            tb.addAction(a)
        # Barra de endereco EDITAVEL: dentro da instancia navega direto; um host NOVO so
        # entra depois de provar que e EBS (validacao em thread, sem travar a janela).
        self.addr = QLineEdit(self)
        self.addr.setPlaceholderText("http://host:porta — so instancias EBS")
        self.addr.setClearButtonEnabled(True)
        self.addr.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.addr.returnPressed.connect(lambda: self.go(self.addr.text()))
        tb.addWidget(self.addr)
        self.lock = QLabel("")
        tb.addWidget(self.lock)
        self._set_lock()
        sc = QShortcut(QKeySequence("Ctrl+L"), self)          # no macOS o Qt mapeia para Cmd+L
        sc.activated.connect(lambda: (self.addr.setFocus(), self.addr.selectAll()))
        sw = QShortcut(QKeySequence("Ctrl+W"), self)          # fecha a aba atual (nunca a Home)
        sw.activated.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        self._val = _Validator(self)
        self._val.done.connect(self._validated)
        self.statusBar()
        self.new_tab(self.ebs_base + "/OA_HTML/AppsLogin", title="Home")

    # ---- abas ----
    def cur(self):
        return self.tabs.currentWidget()

    def new_tab(self, url=None, title="Nova aba"):
        view = QWebEngineView(self.tabs)
        page = EbsPage(self.profile, self)
        view.setPage(page)
        st = page.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        view.urlChanged.connect(lambda u, v=view: self._url_changed(v, u))
        view.titleChanged.connect(lambda t, v=view: self._title_changed(v, t))
        page.windowCloseRequested.connect(lambda v=view: self.close_view(v))   # window.close() do EBS
        i = self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(i)
        if url:
            view.load(QUrl(url))
        return view

    def view_of(self, page):
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).page() is page:
                return self.tabs.widget(i)
        return None

    def close_view(self, view):
        i = self.tabs.indexOf(view)
        if i >= 0:
            self.close_tab(i)

    def close_tab(self, i):
        if i <= 0 or self.tabs.count() <= 1:
            return                                             # a Home nunca fecha
        w = self.tabs.widget(i)
        self.tabs.removeTab(i)
        w.deleteLater()
        log("aba fechada", i)

    def _tab_changed(self, i):
        v = self.tabs.widget(i)
        if v is not None:
            self.addr.setText(v.url().toString())

    def _url_changed(self, view, u):
        if view is self.cur():
            self.addr.setText(u.toString())

    def _title_changed(self, view, t):
        i = self.tabs.indexOf(view)
        if i > 0:                                               # a aba 0 fica sempre "Home"
            self.tabs.setTabText(i, (t or "Aba")[:28])

    def _restore_home(self):
        """Depois de lancar o Forms, garante que a aba Home esta na home do EBS, e nao
        parada no RF.jsp/runforms.jsp por onde o clique passou."""
        v = self.tabs.widget(0)
        u = v.url().toString()
        if re.search(r"RF\.jsp|runforms\.jsp", u):
            if v.history().canGoBack():
                v.back()
            else:
                v.load(QUrl(self.ebs_base + "/OA_HTML/OA.jsp?OAFunc=OANEWHOMEPAGE"))

    def status(self, msg):
        self.statusBar().showMessage(msg, 8000)

    def home(self):
        self.tabs.setCurrentIndex(0)
        self.tabs.widget(0).load(QUrl(self.ebs_base + "/OA_HTML/AppsLogin"))

    def _set_lock(self):
        self.lock.setText(f"   🔒 {self.origin[1]}:{self.origin[2]}   ")
        self.setWindowTitle(f"{APP} — {self.origin[1]}:{self.origin[2]}")

    def go(self, text):
        text = (text or "").strip()
        if not text:
            return
        if "://" not in text:
            text = "http://" + text
        try:
            base = base_of(text)
            p = urlparse(text)
        except Exception:
            self.status("endereco invalido")
            return
        target = text if (p.path and p.path != "/") else base + "/OA_HTML/AppsLogin"
        if origin_of(text) == self.origin:               # mesma instancia: navega direto
            self.cur().load(QUrl(target))
            return
        # host novo: prova que e EBS ANTES de tocar nele (nada e carregado ate la)
        self.addr.setEnabled(False)
        self.status(f"validando {base} como instancia EBS...")
        log("instancia: validando", base)
        threading.Thread(target=lambda: self._val.done.emit(base, target, is_ebs_instance(base)),
                         daemon=True).start()

    def _validated(self, base, target, ok):
        self.addr.setEnabled(True)
        if not ok:
            log("instancia: REJEITADA (nao e EBS)", base)
            self.addr.setText(self.cur().url().toString())
            QMessageBox.critical(self, APP, f"{base} não respondeu como uma instância EBS.\nNão vou abrir.")
            return
        self.ebs_base = base
        self.origin = origin_of(base)
        save_cfg({"ebs_url": base})                      # proxima abertura ja vem nesta instancia
        self._set_lock()
        log("instancia: trocada para", base)
        self.status(f"instância EBS validada: {base}")
        self.cur().load(QUrl(target))

    # ---- downloads: o JNLP do Forms vai para o OpenWebStart como ARQUIVO ----
    def on_download(self, item):
        name = (item.downloadFileName() or "").lower()
        mime = (item.mimeType() or "").lower()
        log("download:", name, "|", mime, "|", item.url().toString()[:150])
        if name.endswith(".jnlp") or "jnlp" in mime:
            d = tempfile.mkdtemp(prefix="ebs-forms-")
            path = os.path.join(d, "forms.jnlp")
            item.setDownloadDirectory(d)
            item.setDownloadFileName("forms.jnlp")
            item.stateChanged.connect(lambda st, p=path: self._jnlp_done(st, p))
            item.accept()
            self.status("Forms: JNLP recebido — abrindo no OpenWebStart…")
        else:
            item.setDownloadDirectory(os.path.expanduser("~/Downloads"))
            item.accept()
            self.status(f"baixando {item.downloadFileName()} em ~/Downloads")

    def _open_ows(self, path):
        if os.path.exists(JWS_JAVA) and os.path.exists(JWS_JAR):
            # -Xnofork: roda o JNLP nesta JVM (o IcedTea por padrao re-lancaria outra)
            cmd = [JWS_JAVA, "-cp", JWS_JAR, "net.sourceforge.jnlp.runtime.Boot", "-Xnofork", path]
            try:
                subprocess.Popen(cmd, stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT)
                log("Forms: runtime JWS embutido chamado (JRE 8 + IcedTea-Web)")
                self.status("Forms: abrindo com o runtime embutido")
                return
            except Exception as e:
                log("Forms: runtime embutido falhou:", e, "- caindo para o OpenWebStart")
        try:
            subprocess.Popen(["open", "-a", OWS_APP, path])
            log("OpenWebStart chamado via open -a com", path)
        except Exception as e:
            log("open -a falhou", e, "- usando o stub")
            subprocess.Popen([OWS_STUB, path])
        self.status("Forms: entregue ao OpenWebStart como arquivo (sem re-buscar a URL)")

    def launch_jnlp_url(self, qurl, page=None):
        u = QUrl(qurl)
        u.setScheme("https" if qurl.scheme() == "jnlps" else "http")
        if u.port() == -1:
            u.setPort(self.origin[2])
        http_url = u.toString()
        if qurl_origin(u) != self.origin:
            log("jnlp fora da instancia, bloqueado:", http_url[:150])
            return
        log("jnlp: buscando UMA vez", http_url[:170])
        self.status("Forms: obtendo o JNLP...")
        try:
            req = urllib.request.Request(http_url, headers={"User-Agent": FIREFOX_UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
                ct = r.headers.get("Content-Type", "")
        except Exception as e:
            log("jnlp: falha ao buscar:", e)
            self.status("Forms: falha ao obter o JNLP (veja o log)")
            return
        if b"<jnlp" not in data[:6000]:
            log("jnlp: resposta NAO e JNLP (ct=%s): %r" % (ct, data[:220]))
            self.status("Forms: o servidor devolveu HTML em vez de JNLP (veja o log)")
            return
        data = _normalize_jnlp(data)
        d = tempfile.mkdtemp(prefix="ebs-forms-")
        path = os.path.join(d, "forms.jnlp")
        with open(path, "wb") as f:
            f.write(data)
        log("jnlp: salvo (entidades normalizadas)", path, len(data), "bytes; entregando ao Java")
        self._open_ows(path)
        # o launcher do Forms nasceu numa aba propria: fecha ela e devolve a Home a home
        v = self.view_of(page) if page is not None else None
        if v is not None:
            QTimer.singleShot(1500, lambda: self.close_view(v))
        QTimer.singleShot(1800, self._restore_home)

    def _jnlp_done(self, st, path):
        S = QWebEngineDownloadRequest.DownloadState
        log("jnlp estado:", st, path)
        if st == S.DownloadInterrupted:
            self.status("Forms: o download do JNLP falhou")
            return
        if st != S.DownloadCompleted:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
            with open(path, "wb") as f:
                f.write(_normalize_jnlp(raw))
        except Exception as e:
            log("jnlp: normalizacao falhou:", e)
        self._open_ows(path)


def main():
    # Syntax.HostAndPort exige porta padrao; espelha http/https. A URL do EBS traz :8000
    # explicito, e launch_jnlp_url adota a porta da instancia se ela vier omitida.
    for sch, port in ((b"jnlp", 80), (b"jnlps", 443)):
        scheme = QWebEngineUrlScheme(sch)
        scheme.setSyntax(QWebEngineUrlScheme.Syntax.HostAndPort)
        scheme.setDefaultPort(port)
        scheme.setFlags(QWebEngineUrlScheme.Flag.CorsEnabled)
        QWebEngineUrlScheme.registerScheme(scheme)
    cfg = load_cfg()
    base = base_of(sys.argv[1]) if len(sys.argv) > 1 else base_of(cfg.get("ebs_url", DEFAULT_EBS))
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    if os.path.exists(ICON_PNG):
        app.setWindowIcon(QIcon(ICON_PNG))   # no macOS isto e o icone do Dock
    if not is_ebs_instance(base):
        QMessageBox.critical(None, APP, f"{base} não é uma instância EBS (ou está fora do ar).\nNada será aberto.")
        sys.exit(2)
    save_cfg({"ebs_url": base})
    w = Browser(base)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
