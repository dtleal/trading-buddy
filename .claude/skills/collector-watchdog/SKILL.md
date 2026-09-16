---
name: collector-watchdog
description: Liga, desliga ou mostra o estado do watchdog do collector MT5 (tarefa MT5OrderflowCollector do Task Scheduler, que relança o collector a cada 1 min e pisca um console no Windows). Use quando o usuário pedir para habilitar/desabilitar/pausar o watchdog, ou reclamar da telinha piscando.
---

# Watchdog do collector (MT5OrderflowCollector)

A tarefa `MT5OrderflowCollector` roda `collector/watchdog.ps1` a cada 1 minuto.
Se não achar um `python.exe` rodando `mt5_orderflow_collector`, ela lança
`collector/run_supervised.bat`. Cada disparo abre um console rápido no Windows
(a "telinha piscando").

Estado atual quando esta skill foi criada (2026-09-15): **desabilitada**.

## O que fazer

Leia o argumento do usuário:

- `on` / `enable` / "liga" → habilitar
- `off` / `disable` / "desliga" / "pausa" → desabilitar
- nada, `status` → só mostrar o estado

### Ver estado
```bash
powershell.exe -NoProfile -Command "Get-ScheduledTask -TaskName MT5OrderflowCollector | Select-Object TaskName,State | Format-List"
```

### Desabilitar (para de piscar; o collector NÃO volta mais sozinho)
```bash
powershell.exe -NoProfile -Command "Disable-ScheduledTask -TaskName MT5OrderflowCollector | Out-Null; (Get-ScheduledTask -TaskName MT5OrderflowCollector).State"
```

### Habilitar
```bash
powershell.exe -NoProfile -Command "Enable-ScheduledTask -TaskName MT5OrderflowCollector | Out-Null; (Get-ScheduledTask -TaskName MT5OrderflowCollector).State"
```

## Depois de desabilitar

O collector vira responsabilidade manual. Para subir na mão (a partir do WSL):

```bash
cd /home/diego && powershell.exe -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\start_collector.bat' -WindowStyle Minimized"
```

Conferir se está alimentando: `curl -s localhost:8000/api/orderflow` — se vier `[]`, o collector caiu.

## Se a tarefa não existir

`Get-ScheduledTask` dá erro "No MSFT_ScheduledTask objects found". Nesse caso ela foi
removida; recriar com:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '\\wsl.localhost\Ubuntu-22.04\home\diego\trading-buddy\collector\install_watchdog_task.ps1'
```

## Resposta ao usuário

Uma linha: o que foi feito e o estado final. Se desabilitou, lembre em uma frase que
o collector agora precisa ser aberto na mão.
