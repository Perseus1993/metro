using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class B1HeroGeometryFactory
    {
        public static GameObject Box(
            Transform parent,
            string name,
            Vector3 position,
            Vector3 scale,
            Material material)
        {
            var instance = GameObject.CreatePrimitive(PrimitiveType.Cube);
            instance.name = name;
            instance.transform.SetParent(parent, false);
            instance.transform.position = position;
            instance.transform.localScale = scale;
            RemoveCollider(instance);
            var renderer = instance.GetComponent<Renderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
            renderer.receiveShadows = true;
            return instance;
        }

        public static GameObject Cylinder(
            Transform parent,
            string name,
            Vector3 position,
            float radius,
            float height,
            Material material)
        {
            var instance = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            instance.name = name;
            instance.transform.SetParent(parent, false);
            instance.transform.position = position;
            instance.transform.localScale = new Vector3(radius * 2f, height * 0.5f, radius * 2f);
            RemoveCollider(instance);
            instance.GetComponent<Renderer>().sharedMaterial = material;
            return instance;
        }

        public static TextMesh Text(
            Transform parent,
            string name,
            string content,
            Vector3 position,
            float characterSize,
            Color color,
            TextAnchor anchor = TextAnchor.MiddleCenter)
        {
            var instance = new GameObject(name);
            instance.transform.SetParent(parent, false);
            instance.transform.position = position;
            instance.transform.rotation = Quaternion.Euler(0f, 180f, 0f);
            var text = instance.AddComponent<TextMesh>();
            text.text = content;
            text.anchor = anchor;
            text.alignment = TextAlignment.Center;
            // TextMesh fontSize controls glyph quality; characterSize controls
            // physical scale. Keep signs architectural rather than UI-sized.
            text.characterSize = characterSize * 0.20f;
            text.fontSize = 72;
            text.color = color;
            text.richText = false;
            var font = Font.CreateDynamicFontFromOSFont(
                new[] { "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Arial" },
                72);
            if (font != null)
            {
                text.font = font;
                text.GetComponent<MeshRenderer>().sharedMaterial = font.material;
            }
            return text;
        }

        private static void RemoveCollider(GameObject instance)
        {
            var collider = instance.GetComponent<Collider>();
            if (collider != null)
            {
                if (UnityEngine.Application.isPlaying)
                    UnityEngine.Object.Destroy(collider);
                else
                    UnityEngine.Object.DestroyImmediate(collider);
            }
        }
    }
}
