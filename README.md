# Cita Monitor Sevilla

Monitor em Python para verificar disponibilidade de cita de Jura de Nacionalidad no Registro Civil de Sevilla pelo portal oficial da Junta de Andalucia.

O bot nao reserva automaticamente, nao resolve captcha e nao tenta burlar protecoes do site. Ele apenas navega de forma conservadora e registra o resultado em CSV.

## Execucao Recomendada

A forma recomendada de manter o monitor rodando e uma VM Ubuntu no Oracle Cloud Free Tier com `cron`.

GitHub Actions pode atrasar execucoes agendadas, especialmente em horarios cheios, e nao e ideal para analisar padrao horario com consistencia. Por isso, o cron em uma VM sempre ligada e preferivel.

Na VM, o projeto deve ficar em:

```txt
/home/ubuntu/cita-monitor-sevilla
```

O CSV fica em:

```txt
/home/ubuntu/cita-monitor-sevilla/data/results.csv
```

Os logs ficam em:

```txt
/home/ubuntu/cita-monitor-sevilla/logs/
```

## Deploy Ubuntu

Veja o passo a passo completo em:

```txt
deploy_ubuntu.md
```

Resumo dos comandos principais:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git unzip curl

cd /home/ubuntu
git clone <REPO_URL> cita-monitor-sevilla
cd cita-monitor-sevilla

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

python check_cita.py
```

## Cron

O cron deve rodar de hora em hora no minuto 7:

```cron
7 * * * * cd /home/ubuntu/cita-monitor-sevilla && /home/ubuntu/cita-monitor-sevilla/.venv/bin/python check_cita.py >> logs/cron.log 2>&1
```

Editar cron:

```bash
crontab -e
```

Listar cron ativo:

```bash
crontab -l
```

Ver logs das ultimas execucoes:

```bash
tail -f /home/ubuntu/cita-monitor-sevilla/logs/cron.log
```

Ver ultimas linhas do CSV:

```bash
tail -n 20 /home/ubuntu/cita-monitor-sevilla/data/results.csv
```

## Execucao Manual

```bash
cd /home/ubuntu/cita-monitor-sevilla
source .venv/bin/activate
python check_cita.py
```

Modo discovery, para mapear o portal e revisar HTML, screenshots e elementos encontrados:

```bash
python check_cita.py --discovery
```

## Variaveis De Ambiente

Crie um arquivo `.env` apenas se quiser mudar opcoes locais:

```env
SAVE_ALL_SCREENSHOTS=false
```

Por padrao, nenhuma notificacao e enviada. Os resultados ficam somente em arquivos.

## Saidas

O CSV tem o formato:

```csv
timestamp,run_id,status,message,url,visible_months_checked,available_dates,screenshot
```

Screenshots principais sao salvos em `screenshots/{run_id}.png` quando o status exige evidencia visual. O modo discovery salva arquivos em:

- `debug/html/`
- `debug/screenshots/`
- `debug/elements.json`

O projeto inclui/cria estas pastas:

- `data/`
- `screenshots/`
- `debug/`
- `logs/`

## Status

- `no_cita`
- `possible_cita`
- `captcha_or_blocked`
- `site_error`
- `script_error`
- `unknown`

## GitHub Actions Opcional

GitHub Actions nao e mais o executor principal. Ele pode ficar no repositorio apenas como teste manual opcional via `workflow_dispatch`.

Para testar manualmente:

```txt
Actions > Check Cita Sevilla > Run workflow
```

Para monitoramento horario real, use a VM Ubuntu com cron.
