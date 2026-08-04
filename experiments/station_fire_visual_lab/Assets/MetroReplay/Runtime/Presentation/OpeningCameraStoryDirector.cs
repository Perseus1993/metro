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
            _exhibitionDestination = ToOrbitView(exhibitionDestination);
            _trainDestination = ToOrbitView(trainDestination);
            _overviewDestination = OpeningCameraStorySampler.CreateOverviewView(stationBounds);
            IsActive = true;
            _camera.SetInputEnabled(false);
            Apply(OpeningCameraStorySampler.Sample(
                0f,
                _artworkTarget,
                _billboardTarget,
                _matchCutDistance,
                _exhibitionDestination,
                _trainDestination,
                _overviewDestination));
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
                OpeningCameraStorySampler.Duration,
                _elapsed + Mathf.Max(0f, unscaledDeltaTime));
            Apply(OpeningCameraStorySampler.Sample(
                _elapsed,
                _artworkTarget,
                _billboardTarget,
                _matchCutDistance,
                _exhibitionDestination,
                _trainDestination,
                _overviewDestination));

            if (_elapsed < OpeningCameraStorySampler.Duration)
                return;

            IsActive = false;
            _camera.SetInputEnabled(true);
        }

        private void Apply(OpeningCameraStorySample sample)
        {
            var view = sample.View;
            _camera.SetView(view.Target, view.Distance, view.Yaw, view.Pitch);
        }

        private static CameraOrbitView ToOrbitView(B1HeroView view)
        {
            return new CameraOrbitView(
                view.Target,
                view.Distance,
                view.Yaw,
                view.Pitch);
        }
    }
}
