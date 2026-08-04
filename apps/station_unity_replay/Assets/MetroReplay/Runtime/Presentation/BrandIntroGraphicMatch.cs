using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class BrandIntroGraphicMatch
    {
        public const float DefaultViewportWidth = 0.30f;

        private static float _viewportWidth = DefaultViewportWidth;

        public static float ViewportWidth => _viewportWidth;

        public static void CaptureViewportWidth(float viewportWidth)
        {
            _viewportWidth = Mathf.Clamp(viewportWidth, 0.12f, 0.72f);
        }

        public static void ResetViewportWidth()
        {
            _viewportWidth = DefaultViewportWidth;
        }

        public static Rect CreateArtworkRect(Rect coinScreenBounds, float artworkAspect)
        {
            var safeAspect = Mathf.Max(0.1f, artworkAspect);
            var width = Mathf.Max(1f, coinScreenBounds.width);
            var height = width / safeAspect;
            return new Rect(
                coinScreenBounds.center.x - width * 0.5f,
                coinScreenBounds.center.y - height * 0.5f,
                width,
                height);
        }
    }
}
