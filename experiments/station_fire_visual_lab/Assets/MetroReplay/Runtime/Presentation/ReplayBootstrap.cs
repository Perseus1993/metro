using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class ReplayBootstrap
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void CreateApplication()
        {
            // The normal interactive Player starts with the brand intro. The
            // intro creates the replay application at its black transition point.
            // Automated/test launches skip the intro and create it immediately.
            if (BrandIntroBootstrap.EnsureIntroExists())
                return;

            EnsureApplicationCreated();
        }

        internal static ReplayApplicationRoot EnsureApplicationCreated()
        {
            var existing = Object.FindFirstObjectByType<ReplayApplicationRoot>();
            if (existing != null)
                return existing;

            return new GameObject("MetroReplayApplication").AddComponent<ReplayApplicationRoot>();
        }
    }
}
