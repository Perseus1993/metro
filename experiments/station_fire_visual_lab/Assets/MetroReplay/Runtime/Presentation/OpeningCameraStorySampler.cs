using UnityEngine;

namespace MetroReplay.Presentation
{
    public enum OpeningCameraStoryBeat
    {
        Billboard,
        DepartureNotice,
        ConcourseReveal,
        Train,
        Overview,
        Complete
    }

    public readonly struct CameraOrbitView
    {
        public Vector3 Target { get; }
        public float Distance { get; }
        public float Yaw { get; }
        public float Pitch { get; }

        public CameraOrbitView(Vector3 target, float distance, float yaw, float pitch)
        {
            Target = target;
            Distance = distance;
            Yaw = yaw;
            Pitch = pitch;
        }
    }

    public readonly struct OpeningCameraStorySample
    {
        public CameraOrbitView View { get; }
        public OpeningCameraStoryBeat Beat { get; }

        public OpeningCameraStorySample(CameraOrbitView view, OpeningCameraStoryBeat beat)
        {
            View = view;
            Beat = beat;
        }
    }

    public static class OpeningCameraStorySampler
    {
        public const float MatchCutHoldEnd = 0.85f;
        public const float BillboardHoldEnd = 2.4f;
        public const float DepartureNoticeEnd = 5.0f;
        public const float ConcourseRevealEnd = 8.5f;
        public const float TrainHoldDuration = 5.0f;
        public const float TrainHoldEnd = ConcourseRevealEnd + TrainHoldDuration;
        public const float OverviewTransitionDuration = 1.4f;
        public const float Duration = TrainHoldEnd + OverviewTransitionDuration;

        public static OpeningCameraStorySample Sample(
            float elapsedSeconds,
            Vector3 artworkTarget,
            Vector3 billboardTarget,
            float matchCutDistance,
            CameraOrbitView exhibitionDestination,
            CameraOrbitView trainDestination,
            CameraOrbitView overviewDestination)
        {
            var elapsed = Mathf.Clamp(elapsedSeconds, 0f, Duration);
            var artworkView = new CameraOrbitView(
                artworkTarget,
                Mathf.Max(0.35f, matchCutDistance),
                180f,
                0f);
            var billboardView = new CameraOrbitView(
                billboardTarget,
                2.8f,
                180f,
                2f);
            var noticeView = new CameraOrbitView(
                Vector3.Lerp(billboardTarget, exhibitionDestination.Target, 0.28f)
                    + Vector3.up * 0.18f,
                7.2f,
                172f,
                6.5f);

            if (elapsed < MatchCutHoldEnd)
                return new OpeningCameraStorySample(
                    artworkView,
                    OpeningCameraStoryBeat.Billboard);

            if (elapsed < BillboardHoldEnd)
            {
                var progress = SmootherStep(Mathf.InverseLerp(
                    MatchCutHoldEnd,
                    BillboardHoldEnd,
                    elapsed));
                var view = Interpolate(artworkView, billboardView, progress);
                return new OpeningCameraStorySample(view, OpeningCameraStoryBeat.Billboard);
            }

            if (elapsed < DepartureNoticeEnd)
            {
                var progress = SmootherStep(Mathf.InverseLerp(
                    BillboardHoldEnd,
                    DepartureNoticeEnd,
                    elapsed));
                return new OpeningCameraStorySample(
                    Interpolate(
                        billboardView,
                        noticeView,
                        progress),
                    OpeningCameraStoryBeat.DepartureNotice);
            }

            var revealProgress = SmootherStep(Mathf.InverseLerp(
                DepartureNoticeEnd,
                ConcourseRevealEnd,
                elapsed));
            if (elapsed <= ConcourseRevealEnd)
            {
                return new OpeningCameraStorySample(
                    Interpolate(noticeView, exhibitionDestination, revealProgress),
                    OpeningCameraStoryBeat.ConcourseReveal);
            }

            if (elapsed <= TrainHoldEnd)
            {
                return new OpeningCameraStorySample(
                    trainDestination,
                    OpeningCameraStoryBeat.Train);
            }

            var overviewProgress = SmootherStep(Mathf.InverseLerp(
                TrainHoldEnd,
                Duration,
                elapsed));
            var overviewView = Interpolate(
                trainDestination,
                overviewDestination,
                overviewProgress);
            var beat = elapsed >= Duration
                ? OpeningCameraStoryBeat.Complete
                : OpeningCameraStoryBeat.Overview;
            return new OpeningCameraStorySample(overviewView, beat);
        }

        public static CameraOrbitView CreateOverviewView(Bounds stationBounds)
        {
            var planDiagonal = new Vector2(
                stationBounds.size.x,
                stationBounds.size.z).magnitude;
            var distance = Mathf.Clamp(
                Mathf.Max(planDiagonal * 0.88f, stationBounds.size.y * 3.5f),
                32f,
                140f);
            return new CameraOrbitView(
                stationBounds.center,
                distance,
                152f,
                6f);
        }

        public static float CalculateFramedDistance(
            float artworkWidth,
            float artworkHeight,
            float verticalFieldOfView,
            float viewportAspect,
            float viewportWidth)
        {
            var tangent = Mathf.Tan(
                Mathf.Clamp(verticalFieldOfView, 1f, 179f)
                * 0.5f
                * Mathf.Deg2Rad);
            var safeAspect = Mathf.Max(0.1f, viewportAspect);
            var safeViewportWidth = Mathf.Clamp(viewportWidth, 0.05f, 1f);
            var horizontalFit = Mathf.Max(0.01f, artworkWidth) * 0.5f
                                / (tangent * safeAspect * safeViewportWidth);
            return Mathf.Max(0.35f, horizontalFit);
        }

        private static CameraOrbitView Interpolate(
            CameraOrbitView from,
            CameraOrbitView to,
            float progress)
        {
            return new CameraOrbitView(
                Vector3.Lerp(from.Target, to.Target, progress),
                Mathf.Lerp(from.Distance, to.Distance, progress),
                Mathf.LerpAngle(from.Yaw, to.Yaw, progress),
                Mathf.Lerp(from.Pitch, to.Pitch, progress));
        }

        private static float SmootherStep(float value)
        {
            var clamped = Mathf.Clamp01(value);
            return clamped * clamped * clamped
                * (clamped * (clamped * 6f - 15f) + 10f);
        }
    }
}
