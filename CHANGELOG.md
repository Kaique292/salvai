# Changelog

## [1.3.0](https://github.com/Kaique292/salvai/compare/v1.2.2...v1.3.0) (2026-10-18)


### ✨ Novidades

* mostra o que muda entre a versão atual e a nova no aviso de atualização ([f1c089f](https://github.com/Kaique292/salvai/commit/f1c089f22e69e8ce611bfa558392aa1d75b2a2ce))
* mostra os aparelhos conectados e permite desconectar cada um ([08a8a84](https://github.com/Kaique292/salvai/commit/08a8a846f819bd84cba24cc1635f2d769bfb85c0))
* procura atualizações toda vez que o app abre e pelo botão Procurar atualizações ([f1c089f](https://github.com/Kaique292/salvai/commit/f1c089f22e69e8ce611bfa558392aa1d75b2a2ce))


### 📝 Documentação

* explica a aba de aparelhos conectados ([61d6516](https://github.com/Kaique292/salvai/commit/61d651675a6fa9023e2ec0c30432a3bfc23a9dac))

## [1.2.2](https://github.com/Kaique292/salvai/compare/v1.2.1...v1.2.2) (2026-10-18)


### 🐛 Correções

* o link do QR code continua funcionando ao abrir no Safari ([867121a](https://github.com/Kaique292/salvai/commit/867121ad571ee0508e0eb0c279ae9e2d7a75688a))

## [1.2.1](https://github.com/Kaique292/salvai/compare/v1.2.0...v1.2.1) (2026-10-18)


### 🐛 Correções

* reabre a versão nova de verdade depois de atualizar ([f5b0999](https://github.com/Kaique292/salvai/commit/f5b09997c9526bd689eb3ed18e99d8500044fd79))


### 📝 Documentação

* adiciona a licença MIT ([29fff6e](https://github.com/Kaique292/salvai/commit/29fff6e7af9b56f967847fdfb4610443e0f19cc9))
* adiciona a verificação do Google Search Console ([0d80f9a](https://github.com/Kaique292/salvai/commit/0d80f9a51188afa70cf8007c9c4d909edb482571))
* melhora a busca do projeto no Google e no GitHub ([c3aae84](https://github.com/Kaique292/salvai/commit/c3aae841bdb55bb2fafa15dab04b84d8164a326d))

## [1.2.0](https://github.com/Kaique292/salvai/compare/v1.1.0...v1.2.0) (2026-10-18)


### ✨ Novidades

* assiste aos vídeos e ouve as músicas direto do computador pelo celular ([5d4a790](https://github.com/Kaique292/salvai/commit/5d4a7909a92ecb8ecf26ff47f121feb3d29e8713))
* envia o link do modo celular pelo WhatsApp com o nome do Wi-Fi ([5d4a790](https://github.com/Kaique292/salvai/commit/5d4a7909a92ecb8ecf26ff47f121feb3d29e8713))
* tira arquivos da lista ou manda para a Lixeira do computador pelo celular, com confirmação ([5d4a790](https://github.com/Kaique292/salvai/commit/5d4a7909a92ecb8ecf26ff47f121feb3d29e8713))


### 🐛 Correções

* esconde o aviso de lista vazia da aba que não está aberta ([5d4a790](https://github.com/Kaique292/salvai/commit/5d4a7909a92ecb8ecf26ff47f121feb3d29e8713))
* o celular mostra e abre só os arquivos baixados pelo Salvaí ([5d4a790](https://github.com/Kaique292/salvai/commit/5d4a7909a92ecb8ecf26ff47f121feb3d29e8713))


### 📝 Documentação

* explica assistir, apagar e compartilhar pelo celular ([dc99933](https://github.com/Kaique292/salvai/commit/dc99933996f2d5fdbac900b0edeb9e4c08f387cb))

## [1.1.0](https://github.com/Kaique292/salvai/compare/v1.0.0...v1.1.0) (2026-10-18)


### ✨ Novidades

* baixa e conecta o conector do Claude automaticamente ([2c3386d](https://github.com/Kaique292/salvai/commit/2c3386de39a8dc93b4676681bca2658a6e0afb48))


### 📝 Documentação

* explica a conexão automática com o Claude ([82dd8a1](https://github.com/Kaique292/salvai/commit/82dd8a11909189e2681181429ae9f8a375874bc8))

## 1.0.0 (2026-10-18)

### ✨ Novidades

- Download de vídeos em MP4 (até 4K) e de músicas em MP3 com capa e título embutidos
- Suporte a YouTube, Instagram, TikTok, X, Facebook, Vimeo e mais de 1.800 sites
- Lista de links com miniatura, título e canal, e configuração de formato e qualidade por link
- Link copiado fora do app já aparece preenchido, pronto para adicionar
- Fila com prioridade: segure e arraste para reordenar; o download atual pausa e continua de onde parou
- Contas conectadas (Instagram, TikTok, X e Facebook) com login pela página oficial e sessão criptografada
- Mensagens claras quando um conteúdo é privado, exige login, foi removido ou foi bloqueado pelo site
- Tela de armazenamento com o espaço usado por categoria e limpeza de cache
- Tema claro e escuro com transição animada
- Tela de carregamento animada com as etapas de abertura
- Conector MCP para o Claude buscar, baixar e organizar vídeos e músicas em pastas
- Salvaí no celular: QR code, página no navegador do celular, pedidos de download e arquivos salvos direto no celular, com retomada de downloads interrompidos
- Bandeja do sistema: ao fechar com downloads em andamento ou com o modo celular ligado, o app continua rodando e avisa com uma notificação
- Atualização automática do app e do motor de download direto pelo app, com verificação SHA-256
- Executável único para Windows, sem precisar instalar nada

### 🔒 Segurança

- Modo celular protegido: só aceita aparelhos da rede local com o código do QR, bloqueia tentativas repetidas e desliga sozinho após 30 minutos sem uso
- Proteção contra sites maliciosos acessando o app pelo navegador (DNS rebinding, CSRF e acesso à rede interna)
- Portas locais exclusivas, sem que outro programa possa ocupar a mesma porta
- Contas criptografadas pelo Windows e atualizações conferidas pelo SHA-256 oficial

### ⚡ Desempenho

- Abertura mais rápida e executável menor
- Downloads com fragmentos em paralelo e pré-visualização de links em cache
- Modo celular só transfere o que mudou
- Limpeza automática das sobras de aberturas fechadas à força
