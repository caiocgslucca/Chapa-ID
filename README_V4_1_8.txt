CHAPA ID V4.1.8 - AUTO REPARO FRONTEND

Correção:
- Evita erro "tsc não é reconhecido" ao iniciar por ZIP.
- Valida node_modules/.bin/tsc.cmd e vite.cmd, não apenas a existência de node_modules.
- Se os executáveis estiverem ausentes, executa npm install automaticamente.
- Se necessário, reconstrói node_modules com npm ci usando package-lock.json.
- Nenhuma configuração manual é exigida.
