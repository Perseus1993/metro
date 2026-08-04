using System;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class OpeningCameraStoryDirector
    {
        private const string ArtworkPath =
            "B1HeroSample/GenWorldCampaignLightbox/GenWorldPerseusArtwork";
        private const string BillboardFacePath =
            "B1HeroSample/GenWorldCampaignLightbox/GenWorldNavyFace";

        private readonly OrbitCameraController _camera;
        private readonly Vector3 _artworkTarget;
        private readonly Vector3 _billboardTarget;
        private readonly float _matchCutDistance;
        private readonly CameraOrbitView _exhibitionDestination;
        private readonly CameraOrbitView _trainDestination;
        private readonly CameraOrbitView _overviewDestination;
        private readonly CameraOrbitView _panoramaStart;
        private readonly CameraOrbitView _panoramaEnd;
        private readonly bool _portrait;
        private readonly float _duration;
        private float _elapsed;

        private OpeningCameraStoryDirector(
            OrbitCameraController camera,
            Vector3 artworkTarget,
            Vector3 billboardTarget,
            float matchCutDistance,
            B1HeroView exhibitionDestination,
            B1HeroView trainDestination,
            Bounds stationBounds)
        {
            _camera = camera ?? throw new ArgumentNullException(nameof(camera));
            _artworkTarget = artworkTarget;
            _billboardTarget = billboardTarget;
            _matchCutDistance = matchCutDistance;
            _portrait = PromotionalVideoCapture.IsPortrait;
            var exhibitionView = ToOrbitView(exhibitionDestination);
            var trainView = ToOrbitView(trainDestination);
            _exhibitionDestination = _portrait
                ? WidenForPortrait(exhibitionView)
                : exhibitionView;
            _trainDestination = _portrait
                ? WidenForPortrait(trainView)
                : trainView;
            _overviewDestination = OpeningCameraStorySampler.CreateOverviewView(stationBounds);
            OpeningCameraStorySampler.CreatePortraitPanoramaScanViews(
                stationBounds,
                out _panoramaStart,
                out _panoramaEnd);
            _duration = _portrait
                ? OpeningCameraStorySampler.PortraitDuration
                : OpeningCameraStorySampler.Duration;
            IsActive = true;
            _camera.SetInputEnabled(false);
            Apply(Sample(0f));
        }

        public bool IsActive { get; private set; }

        public static OpeningCameraStoryDirector TryCreate(
            Transform stationRoot,
            OrbitCameraController camera,
            B1HeroView exhibitionDestination,
            B1HeroView trainDestination,
            Bounds stationBounds)
        {
            if (stationRoot == null || camera == null)
                return null;

            var artwork = stationRoot.Find(ArtworkPath);
            var artworkRenderer = artwork != null ? artwork.GetComponent<Renderer>() : null;
            var face = stationRoot.Find(BillboardFacePath);
            var faceRenderer = face != null ? face.GetComponent<Renderer>() : null;
            if (artworkRenderer == null || faceRenderer == null)
            {
                Debug.LogWarning(
                    "Opening camera story was skipped because the B1 campaign billboard is unavailable.");
                return null;
            }

            var gameCamera = camera.GetComponent<Camera>();
            var matchCutDistance = gameCamera != null
                ? OpeningCameraStorySampler.CalculateFramedDistance(
                    artworkRenderer.bounds.size.x,
                    artworkRenderer.bounds.size.y,
                    gameCamera.fieldOfView,
                    gameCamera.aspect,
                    BrandIntroGraphicMatch.ViewportWidth)
                : 3.40f;

            return new OpeningCameraStoryDirector(
                camera,
                artworkRenderer.bounds.center,
                faceRenderer.bounds.center,
                matchCutDistance,
                exhibitionDestination,
                trainDestination,
                stationBounds);
        }

        public void Tick(float unscaledDeltaTime)
        {
            if (!IsActive)
                return;

            _elapsed = Mathf.Min(
                _duration,
                _elapsed + Mathf.Max(0f, unscaledDeltaTime));
            Apply(Sample(_elapsed));

            if (_elapsed < _duration)
                return;

            IsActive = false;
            _camera.SetInputEnabled(true);
        }

        private void Apply(OpeningCameraStorySample sample)
        {
            var view = sample.View;
            _camera.SetView(view.Target, view.Distance, view.Yaw, view.Pitch);
        }

        private OpeningCameraStorySample Sample(float elapsed)
        {
            if (_portrait)
            {
                return OpeningCameraStorySampler.SamplePortrait(
                    elapsed,
                    _artworkTarget,
                    _billboardTarget,
                    _matchCutDistance,
                    _exhibitionDestination,
                    _trainDestination,
                    _panoramaStart,
                    _panoramaEnd);
            }

            return OpeningCameraStorySampler.Sample(
                elapsed,
                _artworkTarget,
                _billboardTarget,
                _matchCutDistance,
                _exhibitionDestination,
                _trainDestination,
                _overviewDestination);
        }

        private static CameraOrbitView ToOrbitView(B1HeroView view)
        {
            return new CameraOrbitView(
                view.Target,
                view.Distance,
                view.Yaw,
                view.Pitch);
        }

        private static CameraOrbitView WidenForPortrait(CameraOrbitView view)
        {
            return new CameraOrbitView(
                view.Target,
                view.Distance * OpeningCameraStorySampler.PortraitWideShotDistanceMultiplier,
                view.Yaw,
                view.Pitch);
        }
    }
}
