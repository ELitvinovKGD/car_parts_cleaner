# ComfyUI workflows

Экспортируйте проверенный workflow из ComfyUI в **API format** и сохраните JSON
в этой папке. В нужных полях значений используйте точные placeholders:

- `{{IMAGE}}` — имя загруженного crop;
- `{{MASK}}` — имя загруженной бинарной маски;
- `{{PROMPT}}` — инструкция выбранной операции;
- `{{SEED}}` — целочисленный seed;
- `{{OUTPUT_PREFIX}}` — уникальный префикс результата.

Пример фрагмента API workflow:

```json
{
  "10": {
    "class_type": "LoadImage",
    "inputs": {"image": "{{IMAGE}}"}
  },
  "11": {
    "class_type": "LoadImage",
    "inputs": {"image": "{{MASK}}"}
  },
  "20": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "{{PROMPT}}", "clip": ["1", 1]}
  },
  "30": {
    "class_type": "KSampler",
    "inputs": {"seed": "{{SEED}}"}
  },
  "40": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "{{OUTPUT_PREFIX}}"}
  }
}
```

Это только пример привязки полей, а не готовый workflow модели.
