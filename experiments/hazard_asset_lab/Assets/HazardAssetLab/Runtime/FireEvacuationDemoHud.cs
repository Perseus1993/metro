using UnityEngine;

namespace HazardAssetLab
{
    public sealed class FireEvacuationDemoHud : MonoBehaviour
    {
        private GUIStyle titleStyle;
        private GUIStyle bodyStyle;
        private Texture2D panelTexture;
        private float elapsed;

        private void Update()
        {
            elapsed += Time.deltaTime;
        }

        private void OnGUI()
        {
            EnsureStyles();

            Rect panel = new Rect(24f, 24f, 430f, 102f);
            GUI.DrawTexture(panel, panelTexture, ScaleMode.StretchToFill);
            GUI.Label(new Rect(42f, 36f, 390f, 28f), "地铁站台火灾 + 居民跑动视觉样例", titleStyle);

            string state = elapsed < 0.8f
                ? "站台火源出现 / 居民反应中……"
                : "居民正在远离火源，跑向站台两侧出口";
            GUI.Label(new Rect(42f, 67f, 390f, 22f), state, bodyStyle);
            GUI.Label(new Rect(42f, 92f, 390f, 20f), "仅视觉模拟 · 不代表真实疏散模型", bodyStyle);
        }

        private void EnsureStyles()
        {
            if (panelTexture == null)
            {
                panelTexture = new Texture2D(1, 1);
                panelTexture.SetPixel(0, 0, new Color(0.02f, 0.025f, 0.035f, 0.88f));
                panelTexture.Apply();
            }

            titleStyle ??= new GUIStyle(GUI.skin.label)
            {
                fontSize = 19,
                fontStyle = FontStyle.Bold,
                normal = { textColor = new Color(1f, 0.52f, 0.18f) }
            };

            bodyStyle ??= new GUIStyle(GUI.skin.label)
            {
                fontSize = 13,
                normal = { textColor = new Color(0.9f, 0.93f, 0.97f) }
            };
        }

        private void OnDestroy()
        {
            if (panelTexture != null)
            {
                Destroy(panelTexture);
            }
        }
    }
}
