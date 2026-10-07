#!/bin/bash
# Запуск OpenSociometry на macOS
cd "$(dirname "$0")" || exit 1
# на будущее возвращаем файлу право на запуск (оно теряется при некоторых способах распаковки)
chmod +x "$0" 2>/dev/null
if [ -x "OpenSociometry/OpenSociometry" ]; then
  "OpenSociometry/OpenSociometry"
elif command -v python3 >/dev/null 2>&1; then
  python3 app.py
else
  echo "Python 3 не найден. Установите его с https://www.python.org/downloads/ и запустите снова."
  read -p "Нажмите Enter, чтобы закрыть"
fi
