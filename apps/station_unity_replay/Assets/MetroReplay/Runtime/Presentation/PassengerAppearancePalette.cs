using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class PassengerAppearancePalette
    {
        private static readonly Color[] ClothingTints =
        {
            new Color(1.00f, 1.00f, 1.00f),
            new Color(0.88f, 0.96f, 1.00f),
            new Color(0.78f, 0.86f, 1.00f),
            new Color(0.93f, 0.86f, 0.78f),
            new Color(0.84f, 0.94f, 0.84f),
            new Color(0.92f, 0.82f, 0.88f)
        };

        private static readonly Color[] SkinTints =
        {
            new Color(1.00f, 1.00f, 1.00f),
            new Color(1.00f, 0.94f, 0.88f),
            new Color(0.93f, 0.82f, 0.72f),
            new Color(0.80f, 0.68f, 0.58f),
            new Color(0.66f, 0.55f, 0.47f)
        };

        private static readonly Color[] HairTints =
        {
            new Color(0.55f, 0.48f, 0.43f),
            new Color(0.76f, 0.65f, 0.52f),
            new Color(0.40f, 0.43f, 0.47f),
            new Color(0.62f, 0.44f, 0.35f)
        };

        public static int ClothingVariantCount => ClothingTints.Length;
        public static int SkinVariantCount => SkinTints.Length;

        public static int GetBaseIndex(int passengerId, int baseCount)
        {
            if (baseCount <= 0)
                return 0;
            return PositiveHash(passengerId, 0x2c9277b5) % baseCount;
        }

        public static Color GetClothingTint(int passengerId)
        {
            return ClothingTints[PositiveHash(passengerId, 0x68e31da4) % ClothingTints.Length];
        }

        public static Color GetSkinTint(int passengerId)
        {
            return SkinTints[PositiveHash(passengerId, 0x17b7d193) % SkinTints.Length];
        }

        public static Color GetHairTint(int passengerId)
        {
            return HairTints[PositiveHash(passengerId, 0x4cf5ad43) % HairTints.Length];
        }

        private static int PositiveHash(int value, int salt)
        {
            unchecked
            {
                var hash = (uint)(value ^ salt);
                hash ^= hash >> 16;
                hash *= 0x7feb352d;
                hash ^= hash >> 15;
                hash *= 0x846ca68b;
                hash ^= hash >> 16;
                return (int)(hash & 0x7fffffff);
            }
        }
    }
}
