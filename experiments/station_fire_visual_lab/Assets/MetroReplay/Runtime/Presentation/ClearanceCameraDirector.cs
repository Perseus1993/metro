using System;
using System.Collections.Generic;
using MetroReplay.Domain;

namespace MetroReplay.Presentation
{
    internal sealed class ClearanceCameraDirector
    {
        private readonly ReplayData _data;
        private readonly OrbitCameraController _camera;
        private readonly B1HeroView? _b1HeroView;
        private string _dominantLevel;

        public ClearanceCameraDirector(
            ReplayData data,
            OrbitCameraController camera,
            B1HeroView? b1HeroView)
        {
            _data = data ?? throw new ArgumentNullException(nameof(data));
            _camera = camera ?? throw new ArgumentNullException(nameof(camera));
            _b1HeroView = b1HeroView;
        }

        public void Sync(IReadOnlyList<PassengerPose> poses)
        {
            if (!ClearanceHeroViewResolver.TryResolve(
                    _data,
                    poses,
                    out var view,
                    out var dominantLevel))
            {
                return;
            }
            if (string.Equals(_dominantLevel, dominantLevel, StringComparison.Ordinal))
                return;

            _dominantLevel = dominantLevel;
            if (_b1HeroView.HasValue
                && string.Equals(dominantLevel, "b1_concourse", StringComparison.Ordinal))
            {
                view = _b1HeroView.Value;
            }
            _camera.SetView(view.Target, view.Distance, view.Yaw, view.Pitch);
        }
    }
}
