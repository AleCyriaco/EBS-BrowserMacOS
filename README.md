# EBS-Browser (macOS)

> *A dedicated, locked-down browser for Oracle E-Business Suite 12.2 on macOS: renders the OAF web UI with Chromium (QtWebEngine), refuses any non-EBS host at the network layer, and launches Forms via an embedded Java Web Start runtime — no Oracle JRE, no OpenWebStart app required.*

Navegador **dedicado ao Oracle E-Business Suite 12.2** para macOS. Só abre instâncias EBS — validadas antes de qualquer página — e resolve o problema clássico do **Forms (Java Web Start)** em navegadores modernos.

## O que ele faz

| | |
|---|---|
| **Só EBS** | Antes de abrir, prova que o host é uma instância EBS (assinatura do `frmservlet`/OAF). Tudo fora da instância é **bloqueado na camada de rede** — nem imagem, nem script. |
| **OAF (web)** | Engine Chromium (QtWebEngine), perfil persistente (login sobrevive), User-Agent de Firefox — o EBS só gera o JNLP do Forms para UAs que reconhece. |
| **Forms (JWS)** | Intercepta o `jnlp://`, busca o JNLP **uma única vez**, normaliza e entrega o **arquivo** a um runtime Java 8 + IcedTea-Web embutido no `.app`. |
| **Abas** | A Home nunca fecha. Popups e o launcher do Forms abrem em aba nova; a do launcher se fecha sozinha. |
| **Barra de endereço** | Editável. Um host novo só entra depois de validado como EBS (em thread, sem travar); a troca é ao vivo e a última instância fica salva. `Cmd+L` foca, `Cmd+W` fecha a aba. |

## Por que o Forms falha nos navegadores comuns — e como isto resolve

Três armadilhas do EBS 12.2 em modo JWS, todas tratadas no código (`ebs_browser.py`):

1. **O ticket `fsst` é rotacionado a cada requisição válida.** O navegador consome o ticket ao pedir o JNLP; se o cliente JWS *re-busca a URL* (o que OpenWebStart/IcedTea fazem), usa um ticket já gasto e recebe HTML de erro (`Root element is not a jnlp element`). Solução: buscar uma vez e entregar o **arquivo** — o JNLP do EBS não tem `href`, nada precisa ser re-buscado.
2. **Entidades XML numéricas.** O EBS escreve `&#38;`/`&#39;` no JNLP e o parser do IcedTea-Web não as decodifica; o applet recebe `#` literal no `serverURL` e o cliente Forms morre com `MalformedURLException: Illegal character in URL`. Solução: normalizar para `&amp;`/`'` antes de salvar.
3. **`runforms.jsp` navega para `jnlp://host/...`** no macOS. O app registra o scheme e o intercepta.

## Requisitos

- macOS 12+ (Apple Silicon ou Intel)
- Python 3.12+ (testado com 3.13) — [python.org](https://www.python.org/downloads/macos/) ou `brew install python`
- Para o Forms: **JDK 8** e o jar do **OpenWebStart** (o `make-app.sh` os embute no bundle):
  ```bash
  brew install --cask temurin@8 openwebstart
  ```
  O Java 8 para macOS é x86-64 (não existe build arm64); roda via Rosetta em Apple Silicon.

## Instalação

```bash
git clone https://github.com/AleCyriaco/EBS-BrowserMacOS.git
cd EBS-BrowserMacOS
./install.sh      # venv + PySide6
./make-app.sh     # cria /Applications/EBS-Browser.app (e embute o runtime Java, se houver)
open -a EBS-Browser
```

Sem o `.app`: `./run.sh` ou `./run.sh http://host:8000`.

Na primeira abertura, o app pede a instância (padrão `http://apps.example.com:8000`, o hostname do template de VM da Oracle). O EBS redireciona para o **próprio hostname canônico**; use-o na barra, não um IP — o host precisa resolver no Mac (`/etc/hosts`, DNS ou VPN).

Na primeira abertura de um Forms, o IcedTea-Web mostra um *Security Warning* (o JNLP pede `all-permissions`): clique **Run** com *Always trust*. Fica gravado em `~/.config/icedtea-web/`.

## Onde as coisas ficam

| | |
|---|---|
| Config (instância) e perfil do Chromium | `~/Library/Application Support/EBS-Browser/` |
| Log | `~/Library/Logs/EBS-Browser.log` |
| Runtime JWS embutido | `EBS-Browser.app/Contents/Resources/jws/` (JRE 8 + `openwebstart.jar`, ~116 MB) |
| Confiança/cache do IcedTea-Web | `~/.config/icedtea-web/`, `~/.cache/icedtea-web/` |

## Limitações conhecidas

- A barra de menus mostra **"Python"**: o processo gráfico é o `Python.app` do framework. Cosmético; corrigível com PyObjC.
- O venv com QtWebEngine pesa ~1,2 GB (o Chromium é ~540 MB do total). Dá para enxugar módulos Qt não usados, mas o `install.sh` não faz isso por segurança.
- Testado com EBS 12.2.12 (`s_forms_launch_method=jws`).

## Terceiros (não redistribuídos neste repositório)

- [OpenWebStart](https://openwebstart.com/) / IcedTea-Web — GPL-2.0 com Classpath Exception.
- [Eclipse Temurin 8](https://adoptium.net/) — GPL-2.0 com Classpath Exception.
- [PySide6 / Qt](https://www.qt.io/qt-for-python) — LGPL-3.0.

O `make-app.sh` apenas copia esses componentes já instalados na sua máquina para dentro do bundle.

## Licença

MIT — veja `LICENSE`.
