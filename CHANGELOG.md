# Changelog

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
