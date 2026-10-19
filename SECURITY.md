# Segurança

## Como reportar uma vulnerabilidade

Encontrou uma falha de segurança? **Não abra uma issue pública.** Use o botão **Report a vulnerability** na aba [Security](https://github.com/Kaique292/salvai/security) do repositório — a mensagem chega só para o mantenedor. Descreva o problema, como reproduzir e o impacto. A resposta vem em até 7 dias.

Apenas a versão mais recente recebe correções.

## O que o Salvaí faz para proteger você

### Seus dados

- **Sem telemetria.** O app não envia estatísticas nem dados de uso para lugar nenhum.
- O app só fala com: os sites dos links que você cola, o YouTube (para mostrar título e miniatura), o GitHub (para conferir atualizações) e, se o PC não tiver Node.js, o site do Deno (uma única vez).
- **Contas conectadas** ficam só no seu PC, criptografadas com a proteção de dados do Windows (DPAPI) — só o seu usuário do Windows consegue ler. O app nunca vê nem guarda senhas: o login acontece na página oficial de cada site.
- Mensagens de erro enviadas ao celular não revelam caminhos nem detalhes internos do computador.

### Modo celular

- Vem **desligado** e se desliga sozinho depois de 30 minutos sem uso.
- Só aceita aparelhos da **sub-rede da sua casa** (IPv4) ou do mesmo prefixo IPv6; VPNs e outras redes ficam de fora.
- Exige um **código aleatório de 128 bits**, que muda toda vez que o modo é ligado. O código sai da barra de endereço logo no primeiro acesso e fica guardado num cookie `HttpOnly`/`SameSite=Strict`.
- Bloqueia o IP depois de 20 tentativas com código errado, limita pedidos por minuto e o tamanho dos pedidos.
- Recusa pedidos de outros sites (CSRF): todo pedido que muda algo precisa do cabeçalho próprio `X-Salvai` e, se vier com `Origin`, da mesma origem. Também barra ataques de _DNS rebinding_ (só aceita acesso por endereço IP).
- **Enviar para o PC** só aceita aparelhos já conectados pelo QR, grava apenas na pasta **Do celular** (com nomes limpos, sem subpastas, sem `..` e sem sobrescrever nada), confere o espaço livre antes de começar, recebe em pedaços de até 16 MB e apaga os pedaços incompletos quando o modo celular é desligado.
- Só entrega **arquivos de mídia** da pasta de downloads — documentos e outros arquivos nunca saem do PC — e impede acesso fora dessa pasta.
- Envia cabeçalhos de segurança (CSP, `nosniff`, `X-Frame-Options`, `no-referrer`).

### Sala de troca

- Só abre quando você cria a sala e fecha quando você fecha, quando o Salvaí é fechado ou depois de 30 minutos sem uso.
- O servidor da sala escuta só em `127.0.0.1`; quem está fora chega pelo túnel HTTPS da Cloudflare, com um endereço aleatório que muda a cada sala.
- Para entrar é preciso o **código de 6 caracteres** da sala e a **sua aprovação**. Cada convidado recebe uma sessão própria em cookie `Secure`/`HttpOnly`/`SameSite=Strict`, e quem você tira da sala não volta com a mesma sessão.
- Bloqueia o IP depois de 10 tentativas erradas, limita as tentativas da sala inteira e quantas pessoas podem esperar aprovação.
- Recusa pedidos de outros sites (CSRF): todo envio exige um cabeçalho próprio e a origem certa, e o servidor só responde no endereço da sala.
- Só entrega os arquivos e pastas que foram adicionados à sala, por número, nunca por caminho. Nomes vindos de convidados são limpos antes de virar arquivo no seu PC, sem sair da pasta que você escolheu.
- Arquivos enviados chegam em pedaços de até 16 MB, conferidos pela posição; programas (`.exe`, `.bat`, `.msi`, `.ps1`…) aparecem marcados e pedem confirmação antes de baixar.
- O conector da Cloudflare (`cloudflared`) só é baixado das releases oficiais e conferido pelo SHA-256 publicado nelas.

### Conector do Claude (MCP)

- A ponte escuta só em `127.0.0.1`, exige um token que muda a cada abertura e recusa _DNS rebinding_.
- Não apaga arquivos e não sai da pasta de downloads.
- Links vindos do Claude ou do celular para a rede interna ou para o próprio PC (SSRF) são recusados.

### Interface

- Títulos, nomes e miniaturas vindos dos sites nunca são interpretados como código.
- Uma _Content Security Policy_ impede a execução de scripts de fora, mesmo que surja alguma falha no futuro.

### Atualizações e componentes

- Atualizações do app só vêm das releases deste repositório, nunca para uma versão mais antiga, e cada arquivo é conferido pelo SHA-256 publicado na release antes de ser instalado. Se algo falhar no meio, a versão atual continua intacta.
- O motor de download (yt-dlp) e o Deno são conferidos pelo SHA-256 oficial de cada projeto antes de serem usados.
- As GitHub Actions são fixadas por commit, as dependências têm versões fixas e o Dependabot avisa sobre atualizações de segurança.

## Limites conhecidos

- **O modo celular usa HTTP sem criptografia** dentro da sua rede (HTTPS exigiria um certificado que o celular mostraria como inseguro). Em redes compartilhadas ou públicas, alguém na mesma rede poderia ver o tráfego. Use o modo celular só na rede da sua casa e desligue quando não precisar.
- **Na sala de troca, o tráfego passa pela Cloudflare.** A conexão é HTTPS de ponta a ponta entre os aparelhos e a Cloudflare, mas a Cloudflare termina a criptografia no meio do caminho, como em qualquer site que usa o serviço dela. Para arquivos muito sensíveis, compacte com senha antes de mandar.
- **O app não tem assinatura digital paga**, por isso o Windows pode mostrar avisos (veja o README).
- Um programa malicioso que já esteja rodando com o seu usuário do Windows tem acesso aos mesmos arquivos que o Salvaí — nenhum app consegue se proteger disso.
