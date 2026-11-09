# MyVS — локальная студия речи

Локальное веб-приложение для STT, TTS, клонирования голоса, менеджера моделей и
мониторинга ресурсов. Без внешних API и телеметрии: аудио и текст остаются на
машине.

## Возможности

- **STT**: файл (wav/mp3/m4a/ogg) или запись с микрофона, выбор модели и языка,
  таймкоды, экспорт TXT/SRT/VTT/JSON.
- **TTS**: текст → речь, встроенные и клонированные голоса, скорость, тон,
  громкость, длинный текст по фразам.
- **Клонирование**: референс 5–30 секунд, проверка длительности/шума/клиппинга,
  обязательное подтверждение прав, тестовая фраза, голос по описанию для
  поддерживающих моделей.
- **Менеджер моделей**: каталог, скачивание с прогрессом и resume, проверка
  целостности, удаление, ручная загрузка/выгрузка VRAM, добавление своей модели.
- **Ресурсы**: бюджет VRAM/RAM, режимы parallel/economy/exclusive, LRU-выгрузка,
  idle timeout, обработка OOM без падения сервера.
- **Мониторинг**: CPU/GPU/VRAM/RAM/swap/диск, графики за 5 минут, алерты 80/90/100%
  и кнопка «Выгрузить всё» для принудительного освобождения VRAM/RAM.
- **Таймеры**: этапы запуска, live-таймеры задач, RTF, пики ресурсов.

## Быстрый запуск

Требования: Python 3.11–3.12, Node.js 20+, NVIDIA-драйвер (для GPU-моделей),
интернет для первой установки зависимостей и скачивания моделей.

Windows: можно просто дважды кликнуть `start_myvs.bat` — он запустит сервер и
откроет браузер.

```bash
python run.py
```

Откройте `http://127.0.0.1:8000`. `python run.py` создаёт `.venv` (при отсутствии),
устанавливает Python-зависимости, собирает frontend и запускает uvicorn. При
повторных запусках установка пропускается.

Кэш Hugging Face по умолчанию хранится отдельно в `data/models/hf-cache`.
Переменная окружения `HF_HOME`, заданная для других приложений, не меняет
путь кэша MyVS. Для собственного расположения задайте `MYVS_HF_HOME`, например
в PowerShell перед запуском:

```powershell
$env:MYVS_HF_HOME = "D:\\AI\\MyVS-HF-Cache"
python run.py
```

Полезные флаги:

```bash
python run.py --no-browser
python run.py --port 8010
python run.py --dev          # пересобрать frontend + backend reload
python run.py --skip-install # не создавать venv и не ставить зависимости
python run.py --rebuild      # принудительно пересобрать frontend
```

Остановка: кнопка **«Выход»** в правом верхнем углу. Она выгружает все модели
из VRAM/RAM, останавливает воркеры и завершает сервер. Браузер может запретить
автоматическое закрытие вкладки — тогда появится экран «MyVS остановлен».

### Linux

```bash
sudo apt install python3.12 python3.12-venv nodejs npm ffmpeg
python3 run.py
```

### Docker

```bash
docker compose up --build
```

Docker-образ содержит ядро приложения и базовые STT/TTS-зависимости. Для GPU
нужен NVIDIA Container Toolkit и `gpus: all` (уже указан в compose). Тяжёлые
адаптеры (Qwen3-TTS, OmniVoice, Chatterbox, VoxCPM2, GigaAM) в образ не
включены — используйте нативный запуск и `scripts/install_adapters.py`.

## Модели

Стартовый каталог: `backend/models.yaml`. Категории в UI: STT, TTS, TTS с
клонированием. У каждой модели есть лицензия, флаг коммерции, статус русского
языка, VRAM/RAM/disk и варианты квантизации.

| Категория | Модели |
|---|---|
| STT | Faster-Whisper tiny/base/small/medium/large-v3-turbo, GigaAM v2 |
| TTS | Piper, Silero v4, Kokoro-82M |
| Clone | Qwen3-TTS 0.6B Base, Qwen3-TTS 1.7B Base, Qwen3-TTS 1.7B VoiceDesign, Chatterbox Multilingual, Chatterbox Turbo 350M, VoxCPM2, OmniVoice |

Важно:

- **Chatterbox** оставляет PerTh watermark во всех выходных файлах. Приложение
  показывает предупреждение и не удаляет watermark.
- **OmniVoice** — веса CC-BY-NC, только некоммерческое использование.
- **Silero v4** — CC BY-NC 4.0.
- **Kokoro** не поддерживает русский, клонирование и эмоции.
- **VoxCPM2** — 2B, 48 kHz, требует эксклюзивного режима. FP16-вариант не
  помещается в 8 GB с резервом; приложение честно покажет «не влезает» и
  предложит решения. GGUF-путь через llama.cpp-omni не входит в текущую сборку.
- **Qwen3-TTS 1.7B VoiceDesign** — отдельный артефакт, нужен для голоса по
  описанию; Base 1.7B нужен для клонирования.
- Модели Breeze TTS 2, Step Audio EditX, Voxtral, Maya1, Fish S2 Pro, XTTS-v2
  намеренно не включены в стартовый каталог.

### Скачивание

Откройте «Модели», выберите вариант и нажмите «Скачать». Загрузки идут в
`data/models/<model>/<variant>`, поддерживают паузу, продолжение и проверку
размеров/SHA-256 (где upstream публикует хеш). Частичные файлы лежат рядом с
`.part`; после перезапуска загрузка помечается paused.

### Своя модель

В «Модели → Своя модель» укажите id, категорию, adapter, локальный путь,
лицензию и оценки. Для запуска нужен установленный адаптер и совместимая
архитектура. Произвольный Hugging Face-репозиторий не исполняется
автоматически; `trust_remote_code` не используется.

### Тяжёлые адаптеры в отдельных окружениях

Конфликтующие зависимости вынесены в `.venvs/<adapter>`:

```bash
python scripts/install_adapters.py --all
# или выборочно:
python scripts/install_adapters.py omnivoice gigaam
```

Worker запускается интерпретатором нужного окружения, общие CUDA-пакеты берутся
из `.venv`. Это позволяет Chatterbox (transformers 5.2), Qwen3-TTS
(transformers 4.57), OmniVoice (transformers 5.22) и GigaAM жить на одной машине.

## Архитектура

```text
React SPA
  └── REST + WebSocket
        └── FastAPI (один процесс)
              ├── TaskService / priority queue
              ├── ResourceManager (NVML + psutil, reservations)
              ├── Monitor (1 Hz, ring buffer 300 s)
              ├── ModelRegistry (models.yaml + SQLite)
              └── WorkerClient (TCP, spawn per model)
                    ├── .venv (faster-whisper, Piper, Silero, Qwen, Kokoro)
                    ├── .venvs/omnivoice
                    ├── .venvs/chatterbox
                    ├── .venvs/gigaam
                    └── .venvs/voxcpm
```

- API-процесс не импортирует torch. GPU-инференс изолирован в отдельном
  процессе на модель; OOM или зависание убивают воркер, а не сервер.
- Один воркер на загруженную модель, один инференс одновременно. CPU-задачи
  работают параллельно с GPU.
- SQLModel/SQLite: WAL, `foreign_keys=ON`, UTC, миграции через `PRAGMA user_version`.
- WebSocket: `/ws/monitor` (1 Hz), `/ws/tasks/{id}` (прогресс/таймеры),
  `/ws/downloads/{id}` (прогресс).

Структура:

```text
backend/  api/ engines/ services/ db/ models.yaml
frontend/ src/pages src/components src/store
data/     models/ voices/ outputs/ uploads/ tmp/ logs/ app.db
run.py    README.md  docker-compose.yml  Dockerfile
```

## Ресурсы

Формула:

```text
free_vram = total - used - reserve_vram
free_ram  = total - used - reserve_ram
need      = measured_peak или catalog_estimate
verdict   = fits / tight / no
```

Резерв по умолчанию 0.8 GB VRAM и 3 GB RAM. После первого load+warmup замер
пишется в `ModelMeasurement`; дальше используется измеренное значение. На
Windows per-process VRAM через NVML часто недоступна, поэтому применяется
глобальная дельта; это ограничение отражено в UI.

При нехватке памяти приложение предлагает: выгрузить LRU-модель, перевести на
CPU, взять более лёгкую квантизацию или отменить. В режиме «спрашивать» ничего
не делается без выбора. При OOM память освобождается, задача получает
структурированную ошибку, сервер продолжает работать.

## Что проверено на этой машине

Проверялось на Windows 11, RTX 4060 8 GB, драйвер 610.88:

- Faster-Whisper tiny/small: STT, таймкоды, экспорт TXT/SRT/VTT/JSON, RTF.
- Piper RU и Silero v4: TTS, длинный текст, скорость/тон/громкость.
- Kokoro: English TTS.
- Qwen3-TTS 0.6B Base: загрузка, клонирование по 5.3-секундному референсу, TTS.
- OmniVoice 0.6B: загрузка из существующего HF-кэша, auto voice, TTS.
- Chatterbox Multilingual: load, TTS, клонированный голос; PerTh watermark
  подтверждён извлечением (`1.0`).
- GigaAM v2 RNNT: загрузка и транскрипция.
- Параллельный режим: STT small + Qwen3-TTS 0.6B одновременно, без OOM.
- LRU-решение: миссия «не влезает» → выгрузка GigaAM → повторный запуск STT.
- OOM через `vram_limit_gb=0.4`: `409 OOM`, health 200, VRAM освобождён.
- Exclusive: Qwen выгружен на время STT и возвращён после задачи.
- 20 циклов load/unload faster-whisper tiny: дрейф VRAM −0.086 GB, живых
  воркеров не осталось.
- Idle unload: модели выгружены после 5-секундного таймаута.
- Fallback без NVML: сервер стартует, GPU-блок показывает «недоступно».

Не проверялись E2E из-за отсутствия скачанных весов: Qwen3-TTS 1.7B Base,
Qwen3-TTS 1.7B VoiceDesign, Chatterbox Turbo 350M, VoxCPM2, GGUF-вариант.
Их адаптеры и карточки присутствуют, но на этой машине они не запускались.
Docker на машине не установлен, поэтому `docker compose up` не проверялся.

## API

- OpenAPI: `/docs`, `/openapi.json`.
- Основные группы: `/api/health`, `/api/monitor/*`, `/api/models/*`,
  `/api/downloads/*`, `/api/resources/*`, `/api/tasks/*`, `/api/stt/*`,
  `/api/tts/*`, `/api/voices/*`, `/api/settings/*`, `/api/projects/*`.
- Ошибки: `{"error": {"code", "message", "details", "retryable", "actions"}}`.

Подробный отчёт с замерами и известными пробелами: [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).

## Тесты

```bash
.venv/Scripts/python -m pytest -q
npm --prefix frontend run build
```

Приёмочные скрипты:

```bash
python scripts/test_worker.py
python scripts/ui_smoke.py        # нужен запущенный сервер и Edge
python scripts/ui_e2e.py
python scripts/leak_test.py --cycles 20
```

## Известные ограничения

- 8 GB VRAM — тесно: рабочий стол занимает 1–3 GB, часть моделей доступна только
  в exclusive/CPU или с квантизацией.
- VoxCPM2 FP16 не помещается на 8 GB с резервом; GGUF-путь — TODO. Адаптер
  PyTorch присутствует, но веса не скачаны.
- Qwen3-TTS 1.7B на 8 GB требует эксклюзивного режима; веса не скачаны.
- Qwen3-TTS VoiceDesign и Chatterbox Turbo требуют отдельных весов; адаптеры
  есть, E2E не проверялись.
- GigaAM CDN отдаёт просроченный TLS-сертификат; предусмотрен ручной кэш и
  загрузка с отключённой проверкой только для официального CDN.
- Кеш голосовых эмбеддингов Qwen3-TTS/OmniVoice живёт в памяти воркера и
  сбрасывается при выгрузке модели; дисковый кеш — TODO.
- OOM проверен через лимит VRAM 0.4 GB: воркер вернул структурированную ошибку,
  сервер остался жив, память освобождена.
- Первая установка зависимостей требует интернета; дальше приложение работает
  офлайн.
- Docker-образ не содержит тяжёлые адаптеры и не проверялся без Docker.
- Windows per-process VRAM и температура CPU часто недоступны.
- Это локальный single-user сервер без аутентификации; не публикуйте его в сеть
  без reverse proxy и авторизации.

## Лицензии

Код приложения — MIT. Лицензии моделей и голосов указаны в каталоге и карточках.
Пользователь отвечает за право использования клонируемого голоса и соблюдение
лицензий; приложение требует явное подтверждение для клонирования.
