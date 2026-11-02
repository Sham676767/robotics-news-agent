# Локальная библиотека

Рендер читает `library.yaml`: список объектов `file` (локальное имя файла) и
`tags` (список тегов сцены). Например:

```yaml
- file: photo-document.jpg
  tags: [document]
```

Теги берутся из `editorial.scenes` сценария и сопоставляются с таймингами слов.
Выбор по пересечению тегов; при равенстве используются менее показанные материалы.
Без совпадения показывается светлый градиент. Неописанные файлы не участвуют;
папка без манифеста читается как библиотека без тегов и даёт только фон.
Можно использовать PNG/JPEG/WebP и MP4/MOV/MKV/WebM; звук клипов исключён.
Права на добавленные пользователем материалы проверяет владелец библиотеки.

`photo-parcels.jpg`, `photo-phone.jpg`, `photo-document.jpg` созданы встроенным
imagegen для проекта 02.11.2026; чужие кадры Instagram не используются.
Оригиналы сохранены отдельно в `outputs/engaging-reels-demo-v2-2026-11-02/image-sources`.
`01-desk.png` — прежний оригинальный фон, оставлен для совместимости и не включён
в новый манифест. Геометрические картинки с кругами и их генератор удалены.

Набор промптов (режим built-in, use case photorealistic-natural):
- Portrait 9:16 editorial photo: hands packing an unbranded cardboard parcel.
- Portrait 9:16 editorial photo: hand holding a phone with an unreadable screen beside a parcel.
- Portrait 9:16 editorial photo: hands reviewing paper documents with a pen.
Общие требования: natural window light, warm stone/beige with navy accents,
well-lit lower frame, quiet central composition; no text, logos, circles,
diagrams, scales, gavel, vignette or dark gradients. JPEG — экспорт исходных PNG.
