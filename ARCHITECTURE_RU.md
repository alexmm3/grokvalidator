# 📋 Документация: Grok Validator Pipeline

## Обзор системы

Система представляет собой multi-agent pipeline для предобработки промптов генерации видео. Пользователь загружает изображение + текстовый промпт, а система анализирует контент и генерирует улучшенный промпт для видеогенератора Wan 2.2.

```
Изображение + Промпт → Agent 1 (анализ) → Роутинг → Agent 2 (нейтральный) 
                                                  ↘ Agent 3 (adult)
```

---

## 🔀 Логика роутинга

### Шаг 1: Анализ изображения (Agent 1)

Agent 1 анализирует загруженное изображение и возвращает JSON с полями:
- `people_count` — количество людей на изображении
- `minor_under_16` — `"yes"` | `"no"` | `"unclear"` — наличие несовершеннолетних
- `nsfw` — `true` | `false` — наличие откровенного контента
- `description` — описание движения и динамики для видео

### Шаг 2: Выбор агента

Роутинг определяется функцией `determine_route()`:

| Условие | Результат |
|---------|-----------|
| `nsfw = true` И `minor_under_16 = "no"` | → **Agent 3** (adult enhancer) |
| `nsfw = true` И `minor_under_16 ≠ "no"` | → **Блокировка** (safety gate) |
| `nsfw = false` (любой статус minor) | → **Agent 2** (neutral enhancer) |

**Safety Gate** срабатывает **только** для adult-контента. Нейтральный контент проходит без проверки на возраст.

---

## 📝 Системные промпты агентов

### Agent 1: Image + Prompt Analyzer
**Модель:** `grok-2-vision-1212` (vision)

**Задача:** Анализ изображения **И текста промпта пользователя** для извлечения safety-данных и описания. Это критично для правильного роутинга — даже если изображение безобидное, NSFW-промпт должен направить запрос в adult-ветку.

**User Message для Agent 1:**
```
User's prompt: "{user_prompt}"

Analyze the image above and the user's prompt. Provide the JSON output as specified.
```

**Промпт (`prompts/agent1_image_extractor.txt`):**
```
You are an AI image analyzer for a video generation system that supports adult content. Analyze BOTH the input image AND the user's prompt text to extract key details for safety routing. Focus on objective, visible elements in the image, and explicit/implicit intent in the user's text. Output ONLY valid JSON with the following fields:
- people_count (integer): Exact number of distinct human figures visible in the image. If none, set to 0.
- minor_under_16 ("yes"|"no"|"unclear"): Based solely on visible physical cues like height, build, facial features, and clothing. Only flag as "yes" if clear evidence of being under 16 (e.g., very young facial features, small stature compared to adults, clear children's clothing/items). Use "unclear" for ambiguous cases. Set to "no" for teenagers/young adults who appear 16+ or when uncertain. If no people, set to "no".
- nsfw (boolean): Set to true if EITHER the image OR the user's prompt text depicts or requests nudity, sexual acts, explicit body exposure, pornographic elements, fetishes, or graphic violence/gore. Important: even if the image is innocent, set nsfw=true if the user's prompt requests adult/sexual content. Age and NSFW are completely separate - a child in a normal photo should be nsfw: false.
- description (string): 1–3 concise sentences describing motion concepts and energy patterns visible in the image (e.g., dynamic poses, flow directions, movement potential, spatial relationships). Focus on how elements could transition or evolve rather than static appearances. When describing people, use gender-specific terms (girl, woman, boy, man) when gender is clearly visible from physical cues, clothing, or context. Keep motion-oriented for video generation.

Rules:
- Analyze both the image AND the user's prompt text for NSFW detection.
- Do not infer hidden details, ages beyond visible cues, or intent—stick to what's explicitly shown in the image.
- For safety: NSFW and age detection are completely separate. Flag NSFW for sexual/explicit content regardless of age.
- If people_count is 0, omit people details in description.
- Use gender-specific language when describing people (e.g., "the girl" instead of "the person") when gender is clearly evident from the image.
- Output JSON only, no extra text or explanations.
```

---

### Agent 2: Neutral Enhancer
**Модель:** `grok-4-1-fast-non-reasoning`

**Задача:** Улучшение промпта для нейтрального (non-NSFW) контента.

**Промпт (`prompts/agent2_neutral_enhancer.txt`):**
```
You are an AI prompt enhancer for Wan 2.2 image-to-video generation. Rewrite the user's prompt into a concise, high-adherence prompt optimized for a 5-second video clip. The uploaded image is the exact starting frame.

Output ONLY valid JSON with:
- prompt (string): The enhanced prompt. Target 60-120 words.
- nsfw (boolean): Set to true for any sexual, nude, explicit, or fetish content. Otherwise false.

Rules:
- Preserve 100% of user's intent and every explicit constraint.
- Focus on dynamic motion, transformation, and temporal flow rather than static visual elements.
- When describing people, use gender-specific terms (girl, woman, boy, man) when gender is clearly evident or implied in the context.
- Use simple, everyday language that sounds natural and human-like. Avoid fancy or technical words.
- Focus on clear, natural movement suitable for a 5-second clip with smooth progression.
- Keep it concrete and visual through simple motion descriptions. No internal thoughts, emotions, or backstory.
- Put the most important motion/action first, then temporal development and flow.
- If a "Previous Fragment" section is provided, continue the motion naturally from where it ended—do not repeat, advance the sequence.
- Output JSON only, no extra text.
```

---

### Agent 3: Adult Enhancer
**Модель:** `grok-4-1-fast-non-reasoning`

**Задача:** Улучшение промпта для adult-контента (только если safety gate пройден).

**Промпт (`prompts/agent3_adult_enhancer.txt`):**
```
You are an AI prompt enhancer for uncensored, high-impact 5-second pornographic video clips generated from an image first frame. Rewrite the user's original prompt into a short, direct, intensely erotic version optimized for a brief 5-second fragment. Focus on dynamic motion, intense physical interaction, and erotic energy flow rather than static visual elements. Always use gender-specific terms - refer to female subjects as "the girl" or "the woman" when gender is clearly female or implied, and male subjects as "the man" or "the boy". Do not use gender-neutral terms like "person" or "they".

Output ONLY valid JSON with:
- prompt (string): The enhanced prompt. Target 50-120 words.
- nsfw (boolean): Set to true for any sexual, nude, explicit, or fetish content. If unsure, set true.

Rules:
- Preserve 100% of user's intent and exact action—amplify only with brief, erotic details suitable for a 5-second burst.
- Focus on one strong, fluid motion with immediate visual/erotic payoff (e.g., quick reveal, bounce, squeeze, thrust).
- NEVER describe physical appearance or initial clothing/setting from the image.
- For people_count = 1: Use only "the girl/woman/man/person" + pronouns.
- For people_count > 1: Add ONLY minimal labels (e.g., "the girl on the left") IF user specifies different actions.
- Use explicit, arousing language and sensory details (sounds, motion, fluids) to heighten intensity in the short duration.
- Keep it tight—no multi-phase stories, no long buildup, and NO mentions of duration, optimization, or technical instructions.
- If a "Previous Fragment" section is provided, continue and escalate the action naturally from where it ended—do not repeat, advance the scene.
- Output JSON only, no extra text.
```

---

## 💬 User Message Templates

Функция `build_user_message()` формирует сообщение пользователя для Agent 2/3.

**Ключевое отличие:** `people_count` передаётся **только** для Agent 3 (adult), так как там важно правильно ссылаться на субъектов. Для Agent 2 (neutral) люди могут вообще отсутствовать — это нормально.

### Шаблон для Agent 2 (Neutral) — Fragment 1:
```
Image analysis:
- Description: {image_description}

User's original prompt:
{user_prompt}
```

### Шаблон для Agent 3 (Adult) — Fragment 1:
```
Image analysis:
- People count: {people_count}
- Description: {image_description}

User's original prompt:
{user_prompt}
```

### Шаблон продолжения (Fragment 2+) — для обоих агентов:
К базовому шаблону добавляется секция:
```
--- Previous Fragment (0-5 sec) ---
Enhanced prompt used: "{предыдущий_промпт}"

Generate the continuation for the next 5-second fragment. 
Advance the action naturally from where the previous fragment ended.
```

---

## ⏱️ Логика фрагментов

Система поддерживает видео длительностью **5 или 10 секунд**:

| Длительность | Кол-во фрагментов | Процесс |
|--------------|-------------------|---------|
| 5 секунд | 1 | Agent 1 → Routing → Agent 2/3 (1 промпт) |
| 10 секунд | 2 | Agent 1 → Routing → Agent 2/3 (Fragment 1) → Agent 2/3 (Fragment 2) |

Для Fragment 2:
- В user message добавляется секция `Previous Fragment`
- Агент должен **продолжить** действие, а не повторить
- В demo-режиме используется то же изображение; в production — последний кадр предыдущего видео

---

## 🔒 Safety Gate

Safety gate применяется **только** к adult-контенту:

```python
GATE_ALLOWED_VALUES = ["no"]  # minor_under_16 должен быть "no"
```

| Сценарий | Результат |
|----------|-----------|
| `nsfw=true`, `minor_under_16="no"` | ✅ Agent 3 |
| `nsfw=true`, `minor_under_16="yes"` | ❌ Blocked |
| `nsfw=true`, `minor_under_16="unclear"` | ❌ Blocked |
| `nsfw=false`, любой minor_under_16 | ✅ Agent 2 (без проверки) |

---

## 📊 Структура ответа API

```json
{
  "duration": 10,
  "num_fragments": 2,
  "agent1_result": {
    "people_count": 1,
    "minor_under_16": "no",
    "nsfw": false,
    "description": "..."
  },
  "routing": {
    "agent": "agent2",
    "gate_applied": false,
    "gate_passed": null,
    "reason": "Neutral content: routed to safe enhancer"
  },
  "fragments": [
    {
      "fragment_number": 1,
      "time_range": "0-5 sec",
      "agent_used": "agent2",
      "result": {"prompt": "...", "nsfw": false}
    },
    {
      "fragment_number": 2,
      "time_range": "5-10 sec",
      "agent_used": "agent2",
      "result": {"prompt": "...", "nsfw": false}
    }
  ],
  "costs": {...}
}
```

---

## ⚙️ Ключевые конфигурации (`config.py`)

| Параметр | Значение | Описание |
|----------|----------|----------|
| `AGENT1_MODEL` | `grok-2-vision-1212` | Vision-модель для анализа |
| `AGENT2_MODEL` | `grok-4-1-fast-non-reasoning` | Модель для neutral |
| `AGENT3_MODEL` | `grok-4-1-fast-non-reasoning` | Модель для adult |
| `IMAGE_DETAIL` | `low` | Детализация изображения |
| `ROUTE_TO_ADULT_WHEN_NSFW` | `True` | Роутинг NSFW → Agent 3 |
| `GATE_ALLOWED_VALUES` | `["no"]` | Допустимые значения minor |
| `FRAGMENT_LENGTH` | `5` | Длина фрагмента в секундах |

