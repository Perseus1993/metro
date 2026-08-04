using System;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class BrandIntroCrestLayout
    {
        private const byte VisibleAlphaThreshold = 8;

        public static RectInt FindCenteredSquare(
            Color32[] pixels,
            int textureWidth,
            int textureHeight,
            float searchWidthFraction = 0.145f,
            float marginFraction = 0.06f)
        {
            if (pixels == null)
                throw new ArgumentNullException(nameof(pixels));
            if (textureWidth <= 0 || textureHeight <= 0)
                throw new ArgumentOutOfRangeException(
                    nameof(textureWidth),
                    "Texture dimensions must be positive.");
            if (pixels.LongLength != (long)textureWidth * textureHeight)
                throw new ArgumentException(
                    "Pixel count does not match the supplied texture dimensions.",
                    nameof(pixels));

            var searchWidth = Mathf.Clamp(
                Mathf.CeilToInt(textureWidth * Mathf.Clamp(searchWidthFraction, 0.05f, 1f)),
                1,
                textureWidth);
            var minX = searchWidth;
            var minY = textureHeight;
            var maxX = -1;
            var maxY = -1;

            for (var y = 0; y < textureHeight; y++)
            {
                var rowOffset = y * textureWidth;
                for (var x = 0; x < searchWidth; x++)
                {
                    if (pixels[rowOffset + x].a <= VisibleAlphaThreshold)
                        continue;

                    minX = Mathf.Min(minX, x);
                    minY = Mathf.Min(minY, y);
                    maxX = Mathf.Max(maxX, x);
                    maxY = Mathf.Max(maxY, y);
                }
            }

            if (maxX < minX || maxY < minY)
                throw new InvalidOperationException(
                    "No visible crest pixels were found in the left side of the logo texture.");

            var contentWidth = maxX - minX + 1;
            var contentHeight = maxY - minY + 1;
            var margin = Mathf.Max(0f, marginFraction);
            var squareSize = Mathf.CeilToInt(
                Mathf.Max(contentWidth, contentHeight) * (1f + margin * 2f));
            squareSize = Mathf.Clamp(
                squareSize,
                1,
                Mathf.Min(textureWidth, textureHeight));

            var contentCenterX = (minX + maxX) * 0.5f;
            var contentCenterY = (minY + maxY) * 0.5f;
            var squareX = Mathf.Clamp(
                Mathf.RoundToInt(contentCenterX - (squareSize - 1) * 0.5f),
                0,
                textureWidth - squareSize);
            var squareY = Mathf.Clamp(
                Mathf.RoundToInt(contentCenterY - (squareSize - 1) * 0.5f),
                0,
                textureHeight - squareSize);

            return new RectInt(squareX, squareY, squareSize, squareSize);
        }
    }
}
