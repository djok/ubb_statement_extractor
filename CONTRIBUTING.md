# Принос към проекта

Благодарим ви за интереса да допринесете към UBB Statement Extractor!

## Как да допринесете

### Докладване на бъгове

1. Проверете дали бъгът вече не е докладван в [Issues](https://github.com/your-username/ubb-statement-extractor/issues)
2. Ако не е, създайте нов Issue с:
   - Ясно заглавие
   - Описание на проблема
   - Стъпки за възпроизвеждане
   - Очаквано vs. действително поведение
   - Версия на софтуера и среда

### Предлагане на нови функции

1. Отворете Issue с етикет `enhancement`
2. Опишете:
   - Какъв проблем решава функцията
   - Предложена имплементация
   - Възможни алтернативи

### Pull Requests

1. Fork-нете репозиторито
2. Създайте feature branch: `git checkout -b feature/my-feature`
3. Направете промените си
4. Напишете тестове ако е приложимо
5. Commit-нете: `git commit -m 'Add my feature'`
6. Push-нете: `git push origin feature/my-feature`
7. Отворете Pull Request

## Стил на кода

### Python

- Използвайте Python 3.11+
- Следвайте PEP 8
- Използвайте type hints
- Документирайте функции с docstrings

### Commits

- Използвайте ясни commit съобщения
- Една логическа промяна = един commit
- Формат: `type: description`
  - `feat:` нова функционалност
  - `fix:` поправка на бъг
  - `docs:` документация
  - `refactor:` рефакториране
  - `test:` тестове

## Локална разработка

### Setup

```bash
# Клониране
git clone https://github.com/your-username/ubb-statement-extractor.git
cd ubb-statement-extractor

# Виртуална среда
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
.\venv\Scripts\activate   # Windows

# Инсталиране на зависимости
pip install -r requirements.txt
```

### Тестване

```bash
# Стартиране на тестове
pytest

# С coverage
pytest --cov=src
```

### Локално стартиране

```bash
# CLI
PDF_PASSWORD=test python -m src.main test.zip

# API
uvicorn src.api.app:app --reload

# Dashboard
streamlit run src/monitoring/app.py
```

## Сигурност

Ако откриете уязвимост в сигурността, моля НЕ отваряйте публичен Issue. Вместо това, прочетете [SECURITY.md](SECURITY.md).

## Код на поведение

- Бъдете уважителни
- Приемайте конструктивна критика
- Фокусирайте се върху това, което е най-добро за проекта
- Показвайте съпричастност към другите членове на общността

## Въпроси

Ако имате въпроси, отворете Issue с етикет `question`.

Благодарим ви, че допринасяте!
