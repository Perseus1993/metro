from __future__ import annotations

from playwright.sync_api import Page


STORY_LAYER_STYLE = """
#story-image { position: fixed; inset: 0; z-index: 2000000; display: none;
  background: #061321; }
#story-image img { width: 100%; height: 100%; object-fit: cover; }
#story-caption { position: fixed; z-index: 2000002; left: 50%; bottom: 32px;
  transform: translateX(-50%); width: min(1180px, calc(100vw - 80px));
  padding: 18px 28px; border-radius: 16px; color: white;
  background: rgba(4, 16, 29, .90); box-shadow: 0 12px 34px #0008;
  font: 700 28px/1.45 "Microsoft YaHei", sans-serif; text-align: center; }
#story-result { position: fixed; inset: 0; z-index: 2000001; display: none;
  place-items: center; background: rgba(3, 12, 24, .88); color: white;
  font-family: "Microsoft YaHei", sans-serif; }
#story-result .board { width: 980px; padding: 42px; border-radius: 26px;
  background: #0d263f; border: 1px solid #4d87aa; text-align: center; }
#story-result h2 { margin: 0 0 28px; font-size: 42px; }
#story-result .times { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
#story-result .times div { padding: 24px; border-radius: 18px; background: #173652; }
#story-result span { display: block; color: #a9c1d3; font-size: 21px; }
#story-result strong { display: block; margin-top: 10px; color: #ffd166; font-size: 44px; }
#story-result p { margin: 28px 0 0; color: #e8f1f7; font-size: 27px; }
"""


def install_story_layer(page: Page) -> None:
    page.add_style_tag(content=STORY_LAYER_STYLE)
    page.evaluate(
        """() => {
          const image = document.createElement('div'); image.id = 'story-image';
          image.innerHTML = '<img alt="">'; document.body.append(image);
          const caption = document.createElement('div'); caption.id = 'story-caption';
          caption.style.display = 'none'; document.body.append(caption);
          const result = document.createElement('div'); result.id = 'story-result';
          result.innerHTML = `<div class="board"><h2>水马也能清完，但这个位置更慢</h2>
            <div class="times"><div><span>不放水马</span><strong>10分35秒</strong></div>
            <div><span>放了水马</span><strong>13分10秒</strong></div></div>
            <p>多用了 2 分 35 秒，换个位置可能会更合适。</p></div>`;
          document.body.append(result);
        }"""
    )


def show_story_image(page: Page, source: str, message: str, hold_ms: int) -> None:
    page.evaluate(
        """([source, message]) => {
          const layer = document.querySelector('#story-image');
          layer.querySelector('img').src = source; layer.style.display = 'block';
          const text = document.querySelector('#story-caption');
          text.textContent = message; text.style.display = 'block';
        }""",
        [source, message],
    )
    page.wait_for_function("() => document.querySelector('#story-image img')?.complete === true")
    page.wait_for_timeout(hold_ms)
    page.evaluate(
        """() => {
          document.querySelector('#story-image').style.display = 'none';
          document.querySelector('#story-caption').style.display = 'none';
        }"""
    )


def show_caption(page: Page, message: str, hold_ms: int) -> None:
    page.evaluate(
        """message => { const text = document.querySelector('#story-caption');
          text.textContent = message; text.style.display = 'block'; }""",
        message,
    )
    page.wait_for_timeout(hold_ms)
    page.locator("#story-caption").evaluate("element => element.style.display = 'none'")


def show_result(page: Page) -> None:
    pause_playback(page)
    page.locator("#story-result").evaluate("element => element.style.display = 'grid'")


def pause_playback(page: Page) -> None:
    if page.locator("#play").get_attribute("aria-label") == "暂停":
        page.locator("#play").click()


def resume_playback(page: Page) -> None:
    if page.locator("#play").get_attribute("aria-label") == "播放":
        page.locator("#play").click()
