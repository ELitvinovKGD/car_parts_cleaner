# Запуск Body Repair AI

Из корня проекта выполните:

```powershell
.\scripts\start-local.ps1
```

Будут запущены:

- интерфейс: <http://127.0.0.1:8000/?version=reference-annotation>
- ComfyUI: <http://127.0.0.1:8188>
- SAM 2: <http://127.0.0.1:8190/health>

Окно PowerShell должно оставаться открытым. Для остановки нажмите `Ctrl+C`.

Для раздельной отладки запустите в отдельных окнах:

```powershell
.\scripts\start-comfyui.ps1
.\scripts\start-sam2.ps1
.\scripts\start.ps1
```

Проверка: ответ <http://127.0.0.1:8000/api/health> должен содержать
`"status":"ok"`, `"backend":"comfyui"` и `"sam2":true`.

> Обновляйте этот файл вместе со скриптами запуска, портами и обязательными
> компонентами проекта.
