<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logos/rec_call_logo_dark_01.png" />
  <img alt="RecCall" src="logos/rec_call_logo_white_01.png" width="380" />
</picture>

<p><strong>Grave chamadas no macOS — seu microfone + o áudio da reunião — em um único WAV estéreo.</strong></p>

<p>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="gerenciado com uv" src="https://img.shields.io/badge/gerenciado%20com-uv-DE5FE9" />
  <img alt="cobertura 100%" src="https://img.shields.io/badge/cobertura-100%25-2ea44f" />
  <a href="LICENSE"><img alt="licença MIT" src="https://img.shields.io/badge/licen%C3%A7a-MIT-blue" /></a>
</p>

🇬🇧 [English](README.md) &nbsp;·&nbsp; 🇧🇷 **Português**

</div>

---

O RecCall captura o seu microfone e o áudio da reunião (via [BlackHole](https://existential.audio/blackhole/)) e mistura os dois em um único WAV estéreo — **sua voz no canal esquerdo, a chamada no direito** — tudo a partir de um pequeno app web local.

## Recursos

- 🎙️ **Gravação estéreo em uma tomada** — microfone no canal esquerdo, áudio da reunião no direito.
- 📊 **Espectro ao vivo** alimentado pelo áudio real (transmitido do servidor via WebSocket), com contador grande e ícone de status que pisca quando pausado.
- ▶️ **Player integrado** — as gravações salvas tocam no mesmo painel, com espectro real e um botão reproduzir / pausar por linha.
- 🗂️ **Lista de gravações** — id sequencial, duração, qualidade, data/hora de modificação, baixar e excluir (com confirmação), **paginada**.
- 🎚️ **Qualidade configurável** — taxa de amostragem (negociada automaticamente ou forçada) e profundidade de bits (PCM 16/24-bit ou float de 32-bit).
- 🌗 **Temas claro / escuro** com um logo para cada tema.
- 🌐 **Interface bilíngue** — inglês e português do Brasil, alternável na hora.
- ✅ **100% de cobertura de testes no backend** (PortAudio mockado, sem precisar de hardware).

## Índice

- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração de áudio](#configuração-de-áudio)
- [Usando o app](#usando-o-app)
- [Formato dos arquivos](#formato-dos-arquivos)
- [Docker](#docker)
- [Desenvolvimento](#desenvolvimento)
- [Licença](#licença)

## Requisitos

- **macOS** com [Homebrew](https://brew.sh/), e [uv](https://docs.astral.sh/uv/) para rodar o app.
- **[BlackHole 2ch](https://existential.audio/blackhole/)** — driver de áudio virtual usado para capturar o áudio da reunião. Sem ele não existe dispositivo de áudio da reunião para gravar.

> [!IMPORTANT]
> O Docker Desktop no macOS roda dentro de uma VM Linux e não tem acesso direto aos dispositivos CoreAudio (microfone, AirPods, DJI Mic 2, BlackHole). **Rode o RecCall diretamente no host macOS para capturar áudio.** O Docker serve apenas para empacotar a interface/API.

## Instalação

### 1. Instale o BlackHole e as bibliotecas nativas

```bash
brew install blackhole-2ch portaudio libsndfile
```

Isso instala o BlackHole 2ch junto com as bibliotecas PortAudio e libsndfile das quais o RecCall depende.

> [!NOTE]
> Após instalar o BlackHole, pode ser necessário sair e entrar novamente (ou reiniciar) para o macOS registrar o novo dispositivo de áudio.

### 2. Instale o uv e execute o RecCall

```bash
# instale o uv (pule se já tiver)
curl -LsSf https://astral.sh/uv/install.sh | sh

cd RecCall
uv sync          # cria o .venv e instala as dependências a partir do uv.lock
uv run reccall   # inicia o servidor
```

O `uv sync` lê o `pyproject.toml` / `uv.lock` e usa o Python fixado no `.python-version` (3.12), baixando-o automaticamente se necessário.

Depois acesse **<http://localhost:5055>**.

## Configuração de áudio

Só instalar o BlackHole não basta — ele é apenas um "cabo de áudio virtual". Você precisa enviar o áudio da reunião para **ambos**: o seu fone (para você ouvir) **e** o BlackHole (para o RecCall capturar).

**1. Crie um Multi-Output Device**

1. Abra o **Configuração de Áudio e MIDI** (busque pelo Spotlight).
2. Clique no **`+`** no canto inferior esquerdo → **Criar dispositivo de múltiplas saídas**.
3. Marque **os dois**: seu fone/alto-falante real **e** o `BlackHole 2ch`.
4. (Recomendado) Ative o **Drift Correction** na linha do BlackHole.

**2. Direcione o áudio da reunião para ele**

- **Globalmente:** no menu de som do macOS (ou Ajustes do Sistema → Som → Saída), escolha o **Multi-Output Device**.
- **Por app:** dentro do Zoom/Teams/Meet, defina o **Multi-Output Device** como *Saída/Alto-falante*.

**3. Escolha os dispositivos no RecCall** (⚙ Configurações, topo direito):

| Configuração | Vai para | Observações |
| --- | --- | --- |
| **Microfone** | canal esquerdo | `Entrada padrão do macOS` ou um microfone real. Se os AirPods também são a sua saída, use o microfone interno — o macOS deixa o microfone dos AirPods indisponível enquanto eles reproduzem áudio. |
| **Áudio da reunião / BlackHole** | canal direito | escolha **`BlackHole 2ch`**. |
| **Qualidade do som** | — | taxa de amostragem (`Automática` negocia a melhor taxa comum) e profundidade de bits. |

> [!WARNING]
> O Multi-Output Device é só para a **saída** (o som que você ouve). O seu microfone é capturado separadamente — **não** junte mic + BlackHole em um "Aggregate Device", pois o RecCall já mistura os dois nos canais estéreo.

## Usando o app

**Gravador.** O microfone, o dispositivo da reunião e a qualidade selecionados aparecem como chips ao lado do título **Gravador**. Clique em **Gravar** para começar — o contador roda, o ícone de status fica vermelho e o espectro reage ao áudio real. **Pausar** congela e faz o contador piscar, **Continuar** retoma, **Parar** finaliza o WAV.

**Reprodução.** Em **Gravações salvas**, o botão de play é a primeira coluna depois do id. Ele toca a gravação **dentro do painel do gravador** (espectro e contador compartilhados) e vira um botão de pausar. **Fechar** volta ao modo de gravação.

**Lista de gravações.** Colunas: `#`, arquivo, duração, qualidade, tamanho, modificado (data sobre a hora) e ações (baixar, excluir com confirmação). Paginada — altere *Itens por página* nas Configurações.

**Configurações, idioma e tema.** A **⚙ engrenagem** abre dispositivos + qualidade do som + itens por página; o botão **PT/EN** troca o idioma da interface, e o **sol/lua** alterna claro/escuro — tudo lembrado entre recarregamentos.

## Formato dos arquivos

As gravações são salvas em `recordings/YYYY-MM-DD/RecCall_YYYYMMDD_HHMMSS.wav`:

- WAV, **estéreo** — canal esquerdo: microfone · canal direito: áudio da reunião / BlackHole;
- profundidade de bits selecionável em **Configurações → Qualidade do som** (PCM 16-bit por padrão; PCM 24-bit ou float de 32-bit);
- taxa de amostragem negociada automaticamente para a maior suportada pelos dois dispositivos (48 kHz quando disponível), ou forçada pelas Configurações.

## Docker

```bash
docker compose up --build
```

No macOS, isso serve principalmente para validar a interface/API — a captura de áudio não funciona dentro da VM do Docker. No Linux, com dispositivos ALSA/PulseAudio mapeados, a captura pode funcionar adaptando o `docker-compose.yml`.

## Desenvolvimento

```text
backend/app/
  main.py          app FastAPI: rotas REST, /ws/spectrum, mount dos estáticos
  recorder.py      motor de gravação (sounddevice + soundfile), FFT do espectro
  static/          interface web — HTML/CSS/JS puro, sem etapa de build
tests/             suíte pytest (PortAudio mockado)
pyproject.toml     dependências + config do projeto (gerenciado pelo uv)
```

O frontend é HTML/CSS/JS puro servido pelo FastAPI — sem bundler. Em dev, o servidor envia `Cache-Control: no-cache` para os estáticos, e as URLs dos assets levam um `?v=`, então as edições aparecem em um reload normal.

```bash
uv lock --upgrade   # atualiza todas as dependências para as versões mais recentes
uv sync
uv run pytest       # testes do backend — exige 100% de cobertura de linha
```

## Licença

[MIT](LICENSE) © Gustavo Schaedler
