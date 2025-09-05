#!/usr/bin/env python3
"""
Jackify Performance Diagnostic Helper

This utility helps diagnose whether performance issues are in:
1. jackify-engine (.NET binary) - stalls, memory leaks, etc.
2. jackify (Python wrapper) - subprocess handling, threading issues

Usage: python -m jackify.backend.handlers.diagnostic_helper
"""

import time
import psutil
import subprocess
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any


def find_jackify_engine_processes() -> List[Dict[str, Any]]:
    """Find all running jackify-engine and magick (ImageMagick) processes."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'cpu_percent', 'memory_info']):
        try:
            if (
                'jackify-engine' in proc.info['name'] or
                any('jackify-engine' in arg for arg in (proc.info['cmdline'] or [])) or
                proc.info['name'] == 'magick' or
                any('magick' in arg for arg in (proc.info['cmdline'] or []))
            ):
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cmdline': ' '.join(proc.info['cmdline'] or []),
                    'age_seconds': time.time() - proc.info['create_time'],
                    'cpu_percent': proc.info['cpu_percent'],
                    'memory_mb': proc.info['memory_info'].rss / (1024 * 1024) if proc.info['memory_info'] else 0,
                    'process': proc
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def diagnose_stalled_engine(pid: int, duration: int = 60) -> Dict[str, Any]:
    """Monitor a specific jackify-engine process for stalls."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return {"error": f"Process {pid} not found"}
    
    print(f"Monitoring jackify-engine PID {pid} for {duration} seconds...")
    
    samples = []
    start_time = time.time()
    
    while time.time() - start_time < duration:
        try:
            sample = {
                'timestamp': time.time(),
                'cpu_percent': proc.cpu_percent(),
                'memory_mb': proc.memory_info().rss / (1024 * 1024),
                'thread_count': proc.num_threads(),
                'status': proc.status()
            }
            
            try:
                sample['fd_count'] = proc.num_fds()
            except (psutil.AccessDenied, AttributeError):
                sample['fd_count'] = 0
            
            samples.append(sample)
            
            # Real-time status
            status_icon = "🟢" if sample['cpu_percent'] > 10 else "🟡" if sample['cpu_percent'] > 2 else "🔴"
            print(f"{status_icon} CPU: {sample['cpu_percent']:5.1f}% | Memory: {sample['memory_mb']:6.1f}MB | "
                  f"Threads: {sample['thread_count']:2d} | Status: {sample['status']}")
            
            time.sleep(2)
            
        except psutil.NoSuchProcess:
            print("Process terminated during monitoring")
            break
        except Exception as e:
            print(f"Error monitoring process: {e}")
            break
    
    if not samples:
        return {"error": "No samples collected"}
    
    # Analyze results
    cpu_values = [s['cpu_percent'] for s in samples]
    memory_values = [s['memory_mb'] for s in samples]
    
    low_cpu_samples = [s for s in samples if s['cpu_percent'] < 5]
    stall_duration = len(low_cpu_samples) * 2  # 2 second intervals
    
    diagnosis = {
        'samples': len(samples),
        'avg_cpu': sum(cpu_values) / len(cpu_values),
        'max_cpu': max(cpu_values),
        'min_cpu': min(cpu_values),
        'avg_memory_mb': sum(memory_values) / len(memory_values),
        'max_memory_mb': max(memory_values),
        'low_cpu_samples': len(low_cpu_samples),
        'stall_duration_seconds': stall_duration,
        'thread_count_final': samples[-1]['thread_count'] if samples else 0,
        'likely_stalled': stall_duration > 30 and sum(cpu_values[-5:]) / 5 < 5,  # Last 10 seconds low CPU
    }
    
    return diagnosis


def check_system_resources() -> Dict[str, Any]:
    """Check overall system resources that might affect performance."""
    return {
        'total_memory_gb': psutil.virtual_memory().total / (1024**3),
        'available_memory_gb': psutil.virtual_memory().available / (1024**3),
        'memory_percent': psutil.virtual_memory().percent,
        'cpu_count': psutil.cpu_count(),
        'cpu_percent_overall': psutil.cpu_percent(interval=1),
        'disk_usage_percent': psutil.disk_usage('/').percent,
        'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None,
    }


def main():
    """Main diagnostic routine."""
    print("Jackify Performance Diagnostic Tool")
    print("=" * 50)
    
    # Check for running engines and magick processes
    engines = find_jackify_engine_processes()
    
    if not engines:
        print("No jackify-engine or magick processes found running")
        print("\nTo use this tool:")
        print("1. Start a modlist installation in Jackify")
        print("2. Run this diagnostic while the installation is active")
        return
    
    print(f"Found {len(engines)} relevant process(es):")
    for engine in engines:
        age_min = engine['age_seconds'] / 60
        print(f"  PID {engine['pid']}: {engine['name']} {engine['cpu_percent']:.1f}% CPU, "
              f"{engine['memory_mb']:.1f}MB RAM, running {age_min:.1f} minutes, CMD: {engine['cmdline']}")
    
    # Check system resources
    print("\nSystem Resources:")
    sys_info = check_system_resources()
    print(f"  Memory: {sys_info['memory_percent']:.1f}% used "
          f"({sys_info['available_memory_gb']:.1f}GB / {sys_info['total_memory_gb']:.1f}GB available)")
    print(f"  CPU: {sys_info['cpu_percent_overall']:.1f}% overall, {sys_info['cpu_count']} cores")
    print(f"  Disk: {sys_info['disk_usage_percent']:.1f}% used")
    if sys_info['load_average']:
        print(f"  Load average: {sys_info['load_average']}")
    
    # Focus on the engine with highest CPU usage (likely active)
    active_engine = max(engines, key=lambda x: x['cpu_percent'])
    
    print(f"\nMonitoring most active engine (PID {active_engine['pid']}) for stalls...")
    
    try:
        diagnosis = diagnose_stalled_engine(active_engine['pid'], duration=60)
        
        if 'error' in diagnosis:
            print(f"Error: {diagnosis['error']}")
            return
        
        print(f"\n📊 Diagnosis Results:")
        print(f"  Average CPU: {diagnosis['avg_cpu']:.1f}% (Range: {diagnosis['min_cpu']:.1f}% - {diagnosis['max_cpu']:.1f}%)")
        print(f"  Memory usage: {diagnosis['avg_memory_mb']:.1f}MB (Peak: {diagnosis['max_memory_mb']:.1f}MB)")
        print(f"  Low CPU samples: {diagnosis['low_cpu_samples']}/{diagnosis['samples']} "
              f"(stalled for {diagnosis['stall_duration_seconds']}s)")
        print(f"  Thread count: {diagnosis['thread_count_final']}")
        
        # Provide diagnosis
        print(f"\n[DIAGNOSIS]:")
        if diagnosis['likely_stalled']:
            print("[ERROR] ENGINE STALL DETECTED")
            print("   - jackify-engine process shows sustained low CPU usage")
            print("   - This indicates an issue in the .NET Wabbajack engine, not the Python wrapper")
            print("   - Recommendation: Report this to the Wabbajack team as a jackify-engine issue")
        elif diagnosis['avg_cpu'] > 50:
            print("[OK] Engine appears to be working normally (high CPU activity)")
        elif diagnosis['avg_cpu'] > 10:
            print("[WARNING] Engine showing moderate activity - may be normal for current operation")
        else:
            print("[WARNING] Engine showing low activity - monitor for longer or check if installation completed")
            
        # System-level issues
        if sys_info['memory_percent'] > 90:
            print("[WARNING] System memory critically low - may cause stalls")
        elif sys_info['memory_percent'] > 80:
            print("[CAUTION] System memory usage high")
            
        if sys_info['cpu_percent_overall'] > 90:
            print("[WARNING] System CPU usage very high - may indicate system-wide issue")
    
    except KeyboardInterrupt:
        print("\n\n[STOPPED] Monitoring interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Error during diagnosis: {e}")


if __name__ == "__main__":
    main() 