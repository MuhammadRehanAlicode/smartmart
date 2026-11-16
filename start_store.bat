@echo off
setlocal

set "PORT="
set "READY_PORT="
for /f "tokens=1,2 delims=:" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "for ($port=8000; $port -lt 8020; $port++) { $url='http://127.0.0.1:' + $port + '/'; try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200 -and $r.Content -match 'data-hero-slides') { Write-Output ('READY:' + $port); exit 0 } } catch {} }; for ($port=8000; $port -lt 8020; $port++) { $listener=$null; try { $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port); $listener.Start(); $listener.Stop(); Write-Output $port; exit 0 } catch { if ($listener) { $listener.Stop() } } }; exit 1"') do (
  if /i "%%A"=="READY" (set "READY_PORT=%%B") else (set "PORT=%%A")
)
if defined READY_PORT (
  start "" "http://127.0.0.1:%READY_PORT%/#main"
  exit /b 0
)
if not defined PORT (
  echo Could not find an available port for the SmartMart storefront.
  pause
  exit /b 1
)

start "SmartMart Server" /D "%~dp0" python manage.py runserver 127.0.0.1:%PORT%
rem Open the browser only after the storefront homepage responds.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:%PORT%/'; $storeUrl=$url + '#main'; for ($i=0; $i -lt 30; $i++) { try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200 -and $r.Content -match 'data-hero-slides') { Start-Process $storeUrl; exit 0 } } catch { Start-Sleep -Seconds 1 }; Start-Sleep -Seconds 1 }; Write-Host 'SmartMart storefront did not respond. Check the server window for errors.'; pause"

endlocal
