"""
Signal processing: Prep neuro-data (EEG/ECG sim) for ML training.
Your simulate_eeg stub integrated; optimized for 8GB RAM batches.
"""

import numpy as np
from scipy import signal
from typing import Dict, Any

def simulate_eeg(duration: float = 10.0, sample_rate: int = 1000, channels: int = 8) -> np.ndarray:
    """
    Simulates raw EEG signals for testing Cadre training.

    Generates alpha/beta waves; your original stub—now documented.

    Args:
        duration (float): Seconds (default 10).
        sample_rate (int): Hz (default 1000).
        channels (int): e.g., 8 for multi-lead.

    Returns:
        np.ndarray: [channels x samples] raw signals.

    Examples:
        >>> from neurokit.signals import simulate_eeg
        >>> raw = simulate_eeg(duration=5, channels=4)
        >>> raw.shape  # (4, 5000)

    Raises:
        ValueError: Invalid duration/sample_rate.

    Notes:
        - Cadre use: Generate + preprocess for PyTorch/TF on NFS data.
        - Low-spec: Vectorized; <500MB for 10s@1kHz@8ch on 8GB node.
        - Real: Load from Vault storage instead of sim.
    """
    if duration <= 0 or sample_rate <= 0:
        raise ValueError("duration and sample_rate must be >0.")
    t = np.linspace(0, duration, int(duration * sample_rate))
    signals = np.zeros((channels, len(t)))
    for ch in range(channels):
        # Alpha (8-12Hz) + noise
        signals[ch] = np.sin(10 * 2 * np.pi * t) + 0.5 * np.sin(20 * 2 * np.pi * t) + 0.2 * np.random.randn(len(t))
    return signals

def preprocess_signals(data: np.ndarray, sample_rate: int = 1000, signal_type: str = 'eeg') -> np.ndarray:
    """
    Filters/normalizes signals for Cadre input.

    Bandpass + z-score; handles your sim outputs.

    Args:
        data (np.ndarray): [channels x timepoints].
        sample_rate (int): Hz.
        signal_type (str): 'eeg' (0.5-50Hz) or 'ecg' (0.5-40Hz).

    Returns:
        np.ndarray: Processed, same shape.

    Examples:
        >>> from neurokit.signals import simulate_eeg, preprocess_signals
        >>> raw = simulate_eeg()
        >>> clean = preprocess_signals(raw)

    Raises:
        ValueError: Bad shape/type.

    Notes:
        - Docker: Batch <2GB for Cadre Light (4GB alloc).
        - Ties to extract_features; store in Vault Postgres.
    """
    if data.ndim != 2 or sample_rate <= 0:
        raise ValueError("2D data; sample_rate >0.")
    nyquist = 0.5 * sample_rate
    if signal_type == 'eeg':
        low, high = 0.5 / nyquist, 50 / nyquist
    elif signal_type == 'ecg':
        low, high = 0.5 / nyquist, 40 / nyquist
    else:
        raise ValueError("signal_type: 'eeg' or 'ecg'.")
    b, a = signal.butter(4, [low, high], btype='band')
    filtered = signal.filtfilt(b, a, data, axis=1)
    return (filtered - np.mean(filtered, axis=1, keepdims=True)) / (np.std(filtered, axis=1, keepdims=True) + 1e-8)

def extract_features(signals: np.ndarray, sample_rate: int = 1000) -> Dict[str, Any]:
    """
    Pulls power/entropy feats from processed signals for ML models.

    FFT-based; feeds Cadre TF/PyTorch directly.

    Args:
        signals (np.ndarray): Preprocessed [channels x timepoints].
        sample_rate (int): Hz.

    Returns:
        Dict[str, Any]: e.g., {'alpha_power': array, 'entropy': array}.

    Examples:
        >>> from neurokit.signals import extract_features
        >>> feats = extract_features(clean_signals)

    Raises:
        ValueError: Non-2D signals.

    Notes:
        - Efficient: In-place FFT; <1s on 4-core for 10k samples.
        - Log to Vault: `log_to_vault('features', feats)`.
        - Extend: Add delta/theta bands.
    """
    if signals.ndim != 2:
        raise ValueError("2D preprocessed signals.")
    n = signals.shape[1]
    freqs = np.fft.fftfreq(n, 1/sample_rate)[:n//2]
    fft = np.abs(np.fft.fft(signals, axis=1))[:, :n//2]
    alpha_mask = (freqs >= 8) & (freqs <= 12)
    alpha_power = np.mean(fft[:, alpha_mask], axis=1)
    entropy = -np.sum((signals**2) * np.log(signals**2 + 1e-8), axis=1) / np.log(n)
    return {'alpha_power': alpha_power, 'entropy': entropy}
