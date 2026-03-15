import concurrent.futures
import os

import requests

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

words = ["design", "build", "support", "scale"]


def generate_image(word: str, _index: int) -> None:
    prompt = f"A dark, retro-futuristic landing page for a developer tool. Background is deep dark space #0d0d14. Top banner has blocky terminal ASCII text 'TELECLAUDE' with a neon cyan and magenta glow. Below it, text saying 'we {word}.' is brightly highlighted, while other words are muted. Next to the text, floating visual elements representing '{word}' in a technical, 8-bit meets modern UI style (neon lines, abstract UI cards, terminal windows). High contrast, atmospheric, no humans, no cheesy robots. Confident hacker aesthetic."

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"}
    print(f"Generating image for: we {word}.")
    resp = requests.post("https://api.openai.com/v1/images/generations", headers=headers, json=data)

    if resp.status_code == 200:
        url = resp.json()["data"][0]["url"]
        img_data = requests.get(url).content
        filepath = f"todos/public-website-blog/art/hero-{word}.png"
        with open(filepath, "wb") as f:
            f.write(img_data)
        print(f"Saved {filepath}")
    else:
        print(f"Failed for {word}: {resp.text}")


os.makedirs("todos/public-website-blog/art", exist_ok=True)

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(generate_image, words[i], i) for i in range(len(words))]
    concurrent.futures.wait(futures)
