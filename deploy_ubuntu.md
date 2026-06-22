# Deploy Ubuntu - Oracle Cloud Free Tier

Este guia instala o monitor em uma VM Ubuntu no Oracle Cloud Free Tier e configura execucao horaria com `cron`.

## 1. Instalar Dependencias Do Sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git unzip curl
```

## 2. Baixar O Projeto

```bash
cd /home/ubuntu
git clone <REPO_URL> cita-monitor-sevilla
cd cita-monitor-sevilla
```

Substitua `<REPO_URL>` pela URL do repositorio, por exemplo:

```bash
git clone https://github.com/Vinilsx/cita-jura.git cita-monitor-sevilla
```

## 3. Criar E Ativar Venv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4. Instalar Requirements

```bash
pip install -r requirements.txt
```

## 5. Instalar Playwright Chromium

```bash
playwright install chromium
playwright install-deps chromium
```

## 6. Configurar `.env`

O projeto funciona sem `.env`. Para controlar screenshots opcionais:

```bash
cat > .env <<'EOF'
SAVE_ALL_SCREENSHOTS=false
EOF
```

## 7. Testar Execucao Manual

```bash
python check_cita.py
```

Resultado esperado:

```txt
Run ID: ...
Status: no_cita
Message: No hay citas disponibles
CSV updated: /home/ubuntu/cita-monitor-sevilla/data/results.csv
```

O status pode variar se o site estiver indisponivel, bloqueado ou se houver cita possivel.

## 8. Configurar Cron

Editar cron:

```bash
crontab -e
```

Adicionar esta linha:

```cron
7 * * * * cd /home/ubuntu/cita-monitor-sevilla && /home/ubuntu/cita-monitor-sevilla/.venv/bin/python check_cita.py >> logs/cron.log 2>&1
```

Esse cron roda de hora em hora, sempre no minuto 7.

## 9. Listar Cron Ativo

```bash
crontab -l
```

Confirme que aparece:

```cron
7 * * * * cd /home/ubuntu/cita-monitor-sevilla && /home/ubuntu/cita-monitor-sevilla/.venv/bin/python check_cita.py >> logs/cron.log 2>&1
```

## 10. Verificar Logs

```bash
tail -f /home/ubuntu/cita-monitor-sevilla/logs/cron.log
```

## 11. Verificar CSV

```bash
tail -n 20 /home/ubuntu/cita-monitor-sevilla/data/results.csv
```

## 12. Pastas Criadas Pelo Script

O script cria automaticamente:

```txt
data/
screenshots/
debug/
logs/
```

Na VM, os caminhos principais sao:

```txt
/home/ubuntu/cita-monitor-sevilla/data/results.csv
/home/ubuntu/cita-monitor-sevilla/logs/cron.log
```

## 13. Observacao Sobre GitHub Actions

GitHub Actions pode atrasar execucoes agendadas e, em alguns casos, nao disparar exatamente no minuto configurado. Para observar padroes horarios com mais consistencia, mantenha a VM ligada e use `cron` como executor principal.
