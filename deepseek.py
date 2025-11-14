from openai import OpenAI

# for backward compatibility, you can still use `https://api.deepseek.com/v1` as `base_url`.
client = OpenAI(api_key="sk-9167011d9cca455f8b25401328d31f6a", base_url="https://api.deepseek.com")
print(client.models.list())