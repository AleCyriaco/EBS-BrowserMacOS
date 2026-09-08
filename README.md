# EBS-Browser (macOS)

> *A dedicated, locked-down browser for Oracle E-Business Suite 12.2 on macOS — Apple Silicon and Intel. Renders the OAF web UI with Chromium (QtWebEngine), refuses any non-EBS host at the network layer, and opens Forms through an embedded Java Web Start runtime. Ships as a portable `.app`: nothing to install.*

Navegador **dedicado ao Oracle E-Business Suite 12.2** para macOS. Só abre instâncias EBS — validadas antes de qualquer página — e resolve o problema clássico do **Forms (Java Web Start)** nos navegadores modernos. Distribuído como **`.app` portátil**, com tudo dentro.

## Compatibilidade

| Mac | build | observação |
|---|---|---|
| **Apple Silicon** (M1, M2, M3, M4…) | `EBS-Browser-macOS-AppleSilicon-arm64.zip` | nativo. O Java 8 embutido é x86-64 (não existe Java 8 para arm64) e roda via **Rosetta 2** — se ainda não tiver: `softwareupdate --install-rosetta --agree-to-license` |
| **Intel** | `EBS-Browser-macOS-Intel-x86_64.zip` | nativo, inclusive o Java |

macOS 12 (Monterey) ou superior. Um build por chip é deliberado: um binário universal dobraria o Chromium (~250 MB por arquitetura).

## Download portátil (recomendado)

Baixe o zip do seu chip em **[Releases](https://github.com/AleCyriaco/EBS-BrowserMacOS/releases/latest)**, descompacte e arraste `EBS-Browser.app` para `/Applications`. Não precisa de Python, Java nem OpenWebStart instalados — está tudo no bundle (~180–200 MB zipado, ~460–480 MB no disco; o Chromium é a maior parte).

O app é assinado *ad-hoc* (sem conta Apple Developer). Na **primeira abertura** o Gatekeeper avisa: clique com o botão direito → **Abrir**, ou:

```bash
xattr -dr com.apple.quarantine /Applications/EBS-Browser.app
```

## O que ele faz

| | |
|---|---|
| **Só EBS** | Antes de abrir, prova que o host é uma instância EBS (assinatura do `frmservlet`/OAF). Tudo fora da instância é **bloqueado na camada de rede** — nem imagem, nem script. |
| **OAF (web)** | Engine Chromium (QtWebEngine), perfil persistente (login sobrevive), User-Agent de Firefox — o EBS só gera o JNLP do Forms para UAs que reconhece. |
| **Forms (JWS)** | Intercepta o `jnlp://`, busca o JNLP **uma única vez**, normaliza e entrega o **arquivo** ao runtime Java 8 + IcedTea-Web embutido. |
| **Abas** | A Home nunca fecha. Popups e o launcher do Forms abrem em aba nova; a do launcher se fecha sozinha. |
| **Barra de endereço** | Editável. Um host novo só entra depois de validado como EBS (em thread, sem travar); a troca é ao vivo e a última instância fica salva. `Cmd+L` foca, `Cmd+W` fecha a aba. |

## Por que o Forms falha nos navegadores comuns — e como isto resolve

Três armadilhas do EBS 12.2 em modo JWS, todas tratadas em `ebs_browser.py`:

1. **O ticket `fsst` é rotacionado a cada requisição válida.** O navegador consome o ticket ao pedir o JNLP; se o cliente JWS *re-busca a URL* (OpenWebStart/IcedTea fazem isso), usa um ticket já gasto e recebe HTML de erro (`Root element is not a jnlp element`). Solução: buscar uma vez e entregar o **arquivo** — o JNLP do EBS não tem `href`, nada precisa ser re-buscado.
2. **Entidades XML numéricas.** O EBS escreve `&#38;`/`&#39;` no JNLP e o parser do IcedTea-Web não as decodifica; o applet recebe `#` literal no `serverURL` e o cliente Forms morre com `MalformedURLException: Illegal character in URL`. Solução: normalizar para `&amp;`/`'` antes de salvar.
3. **`runforms.jsp` navega para `jnlp://host/...`** no macOS. O app registra o scheme e o intercepta.

## Uso

Na primeira abertura, informe a instância (padrão `http://apps.example.com:8000`, o hostname do template de VM da Oracle). O EBS redireciona para o **próprio hostname canônico** — use-o na barra, não um IP; ele precisa resolver no Mac (`/etc/hosts`, DNS ou VPN).

Na primeira abertura de um Forms, o IcedTea-Web mostra um *Security Warning* (o JNLP pede `all-permissions`): **Run** com *Always trust*. Fica gravado em `~/.config/icedtea-web/`.

| | |
|---|---|
| Config (instância) e perfil do Chromium | `~/Library/Application Support/EBS-Browser/` |
| Log | `~/Library/Logs/EBS-Browser.log` |
| Runtime JWS embutido | `EBS-Browser.app/Contents/Resources/jws/` (JRE 8 + `openwebstart.jar`) |
| Confiança/cache do IcedTea-Web | `~/.config/icedtea-web/`, `~/.cache/icedtea-web/` |

## Rodar do código-fonte

```bash
git clone https://github.com/AleCyriaco/EBS-BrowserMacOS.git
cd EBS-BrowserMacOS
./install.sh      # venv + PySide6 (Python 3.12+)
./run.sh          # ou ./run.sh http://host:8000
./make-app.sh     # opcional: um .app "fino" apontando para este diretório
```

## Gerar o `.app` portátil

```bash
brew install --cask temurin@8 openwebstart   # fornecem o JRE 8 e o openwebstart.jar embutidos
./build-portable.sh arm64                     # ou x86_64 (os dois podem ser gerados no mesmo Mac)
```

O `prune-app.sh` reduz o bundle do PyInstaller de ~500 MB de Qt para o que o app realmente carrega, por **evidência**: calcula o fechamento de dependências com `otool -L` a partir dos módulos importados e remove frameworks, plugins, QML e traduções fora dele — e aborta sem apagar nada se o fechamento não contiver `QtCore`/`QtWebEngineCore`.

## Limitações conhecidas

- Testado com EBS 12.2.12 (`s_forms_launch_method=jws`).
- No modo código-fonte (`run.sh`/`make-app.sh`) a barra de menus mostra "Python"; no `.app` portátil o nome é o correto.

## Terceiros (não redistribuídos no código; embutidos no `.app` portátil conforme suas licenças)

- [OpenWebStart](https://openwebstart.com/) / IcedTea-Web — GPL-2.0 com Classpath Exception.
- [Eclipse Temurin 8](https://adoptium.net/) — GPL-2.0 com Classpath Exception.
- [PySide6 / Qt](https://www.qt.io/qt-for-python) — LGPL-3.0.

## Licença

MIT — veja `LICENSE`.
