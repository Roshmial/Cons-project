# Model fallback logic

## Зафиксированная конфигурация на 178

- Primary provider: `openrouter`
- Primary model: `google/gemma-4-31b-it:free`
- В текущем `config.yaml` явная цепочка `model.fallback_models` не зафиксирована.
- Значит для standalone 178 primary-route считается единственным подтверждённым маршрутом, пока fallback-цепочка не описана явно.

## Практический вывод

- Для развёртки с нуля нужно гарантировать рабочий primary route `openrouter` + `google/gemma-4-31b-it:free`.
- Если позже будет добавлена явная fallback-цепочка, её надо фиксировать здесь и в `config.yaml` одновременно.
- Auxiliary/local inference route в текущем подтверждённом конфиге 178 не зафиксирован, поэтому считать его обязательным по умолчанию нельзя.
