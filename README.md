# Cita Monitor Sevilla

Monitor em Python para verificar disponibilidade de cita de Jura de Nacionalidad no Registro Civil de Sevilla pelo portal oficial da Junta de Andalucia.

O bot nao reserva automaticamente, nao resolve captcha e nao tenta burlar protecoes do site. Ele apenas navega de forma conservadora e registra o resultado em CSV.

## Instalar

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Executar

```bash
python check_cita.py
```

Modo discovery, para mapear o portal e revisar HTML, screenshots e elementos encontrados:

```bash
python check_cita.py --discovery
```

## Variaveis de ambiente

Crie um arquivo `.env` apenas se quiser mudar opcoes locais:

```env
SAVE_ALL_SCREENSHOTS=false
```

Por padrao, nenhuma notificacao e enviada. Os resultados ficam somente em arquivos.

## Saidas

O CSV fica em `data/results.csv` com o formato:

```csv
timestamp,run_id,status,message,url,visible_months_checked,available_dates,screenshot
```

Screenshots principais sao salvos em `screenshots/{run_id}.png` quando o status exige evidencia visual. O modo discovery salva arquivos em:

- `debug/html/`
- `debug/screenshots/`
- `debug/elements.json`

## Status

- `no_cita`
- `possible_cita`
- `captcha_or_blocked`
- `site_error`
- `script_error`
- `unknown`

## GitHub Actions

O workflow em `.github/workflows/check-cita.yml` roda uma vez por hora e tambem pode ser executado manualmente.

Para manter rodando no GitHub:

1. Suba este projeto para um repositorio GitHub.
2. Verifique em `Settings > Actions > General` se Actions esta habilitado.
3. Em `Workflow permissions`, habilite `Read and write permissions` para permitir que o workflow atualize `data/results.csv`.
4. Faca um push para a branch principal.
5. Use `Actions > Check Cita Sevilla > Run workflow` para testar manualmente.

O agendamento `cron: "0 * * * *"` executa no minuto zero de cada hora em UTC. O arquivo `data/results.csv` e commitado de volta no repositorio apos cada execucao. Screenshots e arquivos de debug ficam como artifacts da execucao em `Actions`, para consulta/download.
