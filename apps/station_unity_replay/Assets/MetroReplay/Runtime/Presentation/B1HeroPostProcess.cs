using UnityEngine;

namespace MetroReplay.Presentation
{
    [RequireComponent(typeof(Camera))]
    internal sealed class B1HeroPostProcess : MonoBehaviour
    {
        private Material _material;

        private void Awake()
        {
            var shader = Resources.Load<Shader>("MetroReplayCinematic")
                ?? Shader.Find("Hidden/MetroReplay/Cinematic");
            if (shader != null)
                _material = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
        }

        private void OnRenderImage(RenderTexture source, RenderTexture destination)
        {
            if (_material == null)
            {
                Graphics.Blit(source, destination);
                return;
            }
            Graphics.Blit(source, destination, _material);
        }

        private void OnDestroy()
        {
            if (_material != null)
                Destroy(_material);
        }
    }
}
