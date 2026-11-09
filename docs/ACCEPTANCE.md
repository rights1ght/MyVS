# MyVS — приёмочный отчёт

Дата: 2026-11-09  
Машина: Windows 11, RTX 4060 8192 MiB, драйвер 610.88, Python 3.12.10  
Запуск: `python run.py` → `http://127.0.0.1:8000`

## Что проверено

| Проверка | Результат |
|---|---|
| Один запуск, startup-этапы | `READY in 1215 ms`, этапы в консоли и «О системе» |
| Каталог моделей | 16 карточек, фильтры/лицензии/RU-бейджи отображаются |
| Скачивание small/tiny/Piper/Silero/Kokoro/Qwen/Chatterbox | завершено, прогресс и resume работали |
| Проверка целостности | tiny: `sha256(1/4)+size`, Kokoro: `sha256(8/9)+size` |
| STT Faster-Whisper small | RU/EN, таймкоды, TXT/SRT/VTT/JSON |
| TTS Piper RU + Silero v4 | синтез, длинный текст, скорость/тон/громкость |
| TTS Kokoro | English, RTF 0.319 |
| Qwen3-TTS 0.6B | клонирование по 5.3-секундному референсу + TTS |
| OmniVoice 0.6B | auto voice через существующий HF-кэш |
| Chatterbox Multilingual | load, auto voice, клонированный голос; PerTh watermark = 1.0 |
| GigaAM v2 RNNT | load 3.3 s, транскрипция 6.6-секундного файла, RTF 0.260 |
| Параллельный STT + TTS (GPU) | small + Qwen3-TTS 0.6B одновременно, без OOM |
| Параллельный CPU + GPU | Piper TTS и faster-whisper small пересекаются по времени |
| Проекты | STT-задача с project_id; удаление проекта сохраняет историю, очищая project_id |
| Чистая БД | запуск с пустым data: 16 моделей, 20 голосов, 0 задач |
| LRU/no-fit | «не влезает» → выгрузка GigaAM → повторный запуск |
| Idle unload | 5-секундный таймаут выгрузил обе модели |
| Leak-тест 20 циклов | дрейф VRAM −0.086 GB, воркеров не осталось |
| OOM | VRAM cap 0.4 GB → Chatterbox load вернул `409 OOM`; health 200, VRAM освобождён |
| Exclusive restore | Qwen выгружен на время STT, после задачи автоматически возвращён |
| Выгрузить всё | `POST /api/resources/unload-all` выгрузил tiny + Piper, `count=2`, loaded=[] |
| Выход | `POST /api/system/shutdown` выгрузил tiny, сервер завершился с кодом 0, VRAM освобождена |
| No-GPU fallback | сервер стартует, GPU-блок «недоступно», CPU работает |
| Frontend | production build, тёмная/светлая темы, мобильная навигация |
| Backend tests | 10 passed |

## Параллельный режим

Задачи запущены одновременно:

- STT `faster-whisper-small`, старт `21:38:16.933`, финиш `21:38:20.207`,
  `load_ms=2719`, `infer_ms=537`, RTF `0.0811`.
- TTS `qwen3-tts-0.6b`, старт `21:38:17.103`, финиш `21:38:34.284`,
  `load_ms=8875`, `infer_ms=8269`, RTF `2.1534`.

Интервалы пересекаются, обе модели одновременно находились в VRAM. Итоговый
статус ресурсов: STT ~0.37 GB, Qwen ~2.75 GB, свободно ~2.2 GB при резерве 0.8 GB.

CPU + GPU:

- STT small: `22:48:36.269` → `22:48:39.853`, RTF 0.064.
- Piper TTS: `22:48:36.476` → `22:48:42.238`, RTF 0.112.

Задачи пересекаются, TTS шёл на CPU, STT — на GPU.

## Замеры и таймеры

- Qwen3-TTS 0.6B: load 22.2 s, infer 11.9 s на 4.96 s аудио, RTF 2.39.
- Chatterbox: VRAM 3.07 GB, infer 18.0 s на 5.4 s, RTF 3.34.
- Kokoro: load 36.4 s, infer 0.91 s на 2.85 s, RTF 0.319.
- GigaAM: load 3.34 s, infer 1.73 s на 6.6 s, RTF 0.260.
- Piper: нагрузка/инференс с длинным текстом, отмена задачи между чанками.
- Задачи сохраняют queue/load/infer/post/total, RTF, пики CPU/GPU/VRAM/RAM/температуры.

## Пробелы приёмки

Не скачаны и не проверены E2E (по решению пользователя — оставить текущий набор):

- Qwen3-TTS 1.7B Base;
- Qwen3-TTS 1.7B VoiceDesign;
- Chatterbox Turbo 350M;
- VoxCPM2 (FP16 не помещается в 8 GB с резервом; GGUF-путь — TODO).

Docker на машине не установлен, `docker compose up` не проверялся.
Linux native не проверялся (WSL отсутствует).
OOM проверен через `vram_limit_gb=0.4`: воркер упал с OOM, сервер остался жив,
память освобождена. Task-level OOM также дал `failed` с кодом `OOM`, health 200.
Docker/Linux остаются непроверенными.
