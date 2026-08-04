using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class PassengerAnimationPlayer
    {
        public static void Configure(Animation animation)
        {
            if (animation == null)
                return;
            animation.playAutomatically = false;
            animation.cullingType = AnimationCullingType.BasedOnRenderers;
            foreach (AnimationState state in animation)
                state.wrapMode = WrapMode.Loop;
        }

        public static void Play(
            Animator animator,
            Animation animation,
            ref string currentName,
            string requestedName,
            int passengerId)
        {
            if (currentName == requestedName)
                return;
            if (animator != null)
                PlayAnimator(animator, requestedName, passengerId);
            else if (animation != null)
                PlayLegacy(animation, requestedName, passengerId);
            currentName = requestedName;
        }

        private static void PlayAnimator(Animator animator, string name, int passengerId)
        {
            var hash = Animator.StringToHash(name);
            if (!animator.HasState(0, hash))
                hash = Animator.StringToHash("Idle_Loop");
            animator.CrossFade(hash, 0.12f, 0, Phase(passengerId));
        }

        private static void PlayLegacy(Animation animation, string name, int passengerId)
        {
            if (animation.GetClip(name) == null)
                name = animation.GetClip("Idle_Loop") != null
                    ? "Idle_Loop"
                    : animation.clip != null ? animation.clip.name : null;
            if (string.IsNullOrEmpty(name) || animation[name] == null)
                return;
            animation[name].wrapMode = WrapMode.Loop;
            animation[name].normalizedTime = Phase(passengerId);
            animation.CrossFade(name, 0.12f);
        }

        private static float Phase(int passengerId) =>
            Mathf.Repeat(passengerId * 0.61803398875f, 1f);
    }
}
