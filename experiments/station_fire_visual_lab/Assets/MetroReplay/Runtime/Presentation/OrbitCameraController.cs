using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class OrbitCameraController : MonoBehaviour
    {
        private const float MinimumDistance = 0.35f;
        private Vector3 _target;
        private float _distance;
        private float _yaw = -20f;
        private float _pitch = 42f;

        public bool InputEnabled { get; private set; } = true;

        public void Frame(Bounds bounds)
        {
            _target = bounds.center;
            _distance = Mathf.Max(18f, bounds.extents.magnitude * 1.45f);
            ApplyTransform();
        }

        public void SetView(Vector3 target, float distance, float yaw, float pitch)
        {
            _target = target;
            _distance = Mathf.Clamp(distance, MinimumDistance, 220f);
            _yaw = yaw;
            _pitch = Mathf.Clamp(pitch, 0f, 82f);
            ApplyTransform();
        }

        public void SetInputEnabled(bool enabled)
        {
            InputEnabled = enabled;
        }

        private void LateUpdate()
        {
            if (InputEnabled)
            {
                if (Input.GetMouseButton(1))
                {
                    _yaw += Input.GetAxis("Mouse X") * 4f;
                    _pitch = Mathf.Clamp(_pitch - Input.GetAxis("Mouse Y") * 3f, 12f, 82f);
                }

                var verticalInput = 0f;
                if (Input.GetKey(KeyCode.Q) || Input.GetKey(KeyCode.PageDown))
                    verticalInput -= 1f;
                if (Input.GetKey(KeyCode.E) || Input.GetKey(KeyCode.PageUp))
                    verticalInput += 1f;

                if (Mathf.Abs(verticalInput) > 0.001f)
                {
                    var moveSpeed = Mathf.Max(2f, _distance * 0.15f);
                    _target += Vector3.up * (verticalInput * moveSpeed * Time.unscaledDeltaTime);
                }
            }

            var scroll = InputEnabled ? Input.mouseScrollDelta.y : 0f;
            if (Mathf.Abs(scroll) > 0.001f)
                _distance = Mathf.Clamp(
                    _distance * Mathf.Pow(0.9f, scroll),
                    MinimumDistance,
                    220f);
            ApplyTransform();
        }

        private void ApplyTransform()
        {
            var rotation = Quaternion.Euler(_pitch, _yaw, 0f);
            transform.SetPositionAndRotation(_target - rotation * Vector3.forward * _distance, rotation);
        }
    }
}
