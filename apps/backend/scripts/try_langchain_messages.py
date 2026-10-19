"""Manual LangChain message smoke test.

`SystemMessage`, `HumanMessage`, and `AIMessage` are plain objects. Building
and printing them does not call an API. `chat.invoke(messages)` does: it sends
the list to Gemini with `GEMINI_API_KEY` and `GEMINI_MODEL_CHAT` from `.env`.

Run from `apps/backend`:

    uv run python scripts/try_langchain_messages.py
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def main() -> None:
    messages = [
        SystemMessage(content="You are a concise Spanish tutor. Reply in one short sentence."),
        HumanMessage(content="How do I say 'good morning' in Spanish?"),
        # AIMessage(content="Buenos días."),
        # HumanMessage(content="And how do I reply if someone says that to me?"),
    ]

    print("Local messages (no API call yet):")
    for message in messages:
        print(f"  {type(message).__name__} type={message.type!r} content={message.content!r}")

    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to apps/backend/.env")

    chat = ChatGoogleGenerativeAI(
        model=settings.gemini_model_chat,
        api_key=settings.gemini_api_key,
        temperature=None,
        max_retries=0,
        timeout=settings.gemini_timeout_seconds,
    )
    
    
    response = chat.invoke(messages)

    

    # print(f"\nGemini reply ({settings.gemini_model_chat}):")
    print(response.content[0]['text'])


if __name__ == "__main__":
    main()
