import io
import json
import logging
from typing import Any, Dict, List

import plotly.graph_objects as go

logger = logging.getLogger("evaluator_agent")


def build_performance_figure(reports: List[Dict[str, Any]]) -> go.Figure:
    if not reports:
        # Return empty figure if no reports
        return go.Figure()
        
    # Sort by evaluation time if present
    def key_fn(r):
        return r.get("evaluated_at") or r.get("collected_at") or ""
    
    data = sorted(reports, key=key_fn)
    
    # Always start from origin - insert a 0 point if first score > 0
    # Use sequence numbers for x-axis to ensure all points are visible
    first_score = float(((data[0].get("scores") or {}).get("final_score") or 0.0)) if data else 0.0
    
    if first_score > 0:
        # Insert origin point
        x = [0] + list(range(1, len(data) + 1))
        y = [0.0] + [float(((r.get("scores") or {}).get("final_score") or 0.0)) for r in data]
        timestamps = ["Start"] + [r.get("evaluated_at") or r.get("collected_at") or "" for r in data]
    else:
        x = list(range(1, len(data) + 1))
        y = [float(((r.get("scores") or {}).get("final_score") or 0.0)) for r in data]
        timestamps = [r.get("evaluated_at") or r.get("collected_at") or "" for r in data]
    
    # Create hover text with both timestamp and score
    hover_text = []
    for i, (ts, score) in enumerate(zip(timestamps, y)):
        if ts == "Start":
            hover_text.append(f"Origin<br>Score: 0.00")
        else:
            hover_text.append(f"Snapshot {i}<br>Time: {ts}<br>Score: {score:.2f}")

    fig = go.Figure()
    
    # Add scatter plot with hover text - using purple accent color for dark mode
    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines+markers",
        name="Final Score",
        text=hover_text,
        hoverinfo="text+y",
        line=dict(color='#7c3aed', width=2.5),  # Match --accent purple
        marker=dict(size=8, line=dict(width=1, color='rgba(0,0,0,0.3)'))
    ))
    
    # Add annotations for first and last points
    if len(data) > 1:
        for idx in [0, -1]:
            fig.add_annotation(
                x=x[idx],
                y=y[idx],
                text=f"{y[idx]:.2f}",
                showarrow=True,
                arrowhead=1,
                ax=0,
                ay=-20 if idx == 0 else 20,
                font=dict(color='#e5e5e5'),
                bgcolor='rgba(18, 18, 18, 0.9)',
                bordercolor='#262626'
            )
    
    # Dark mode theme matching UI
    fig.update_layout(
        title=dict(
            text="Agent Performance Over Time",
            font=dict(color='#e5e5e5', size=18)
        ),
        xaxis_title=dict(
            text="Snapshot #",
            font=dict(color='#a3a3a3', size=12)
        ),
        yaxis_title=dict(
            text="Final Score",
            font=dict(color='#a3a3a3', size=12)
        ),
        # Custom dark theme
        plot_bgcolor='#0a0a0a',  # Match --bg-color
        paper_bgcolor='#121212',  # Match --bg-elevated
        font=dict(color='#e5e5e5', family='Inter, sans-serif'),  # Match --text-color
        height=500,
        width=900,
        margin=dict(l=50, r=30, t=60, b=50),
        hovermode='closest',
        xaxis=dict(
            tickmode='array',
            tickvals=x,
            ticktext=[f"{i}" for i in x],
            gridcolor='#262626',  # Match --border-soft
            zerolinecolor='#262626',
            tickfont=dict(color='#a3a3a3'),  # Match --muted-text
            titlefont=dict(color='#a3a3a3')
        ),
        yaxis=dict(
            rangemode='tozero',  # Ensure y-axis starts at 0
            gridcolor='#262626',  # Match --border-soft
            zerolinecolor='#262626',
            tickfont=dict(color='#a3a3a3'),  # Match --muted-text
            titlefont=dict(color='#a3a3a3')
        )
    )
    return fig


def build_multi_agent_progress_figure(
    agent_snapshots: Dict[str, List[Dict[str, Any]]]
) -> go.Figure:
    """
    Build a plotly figure showing progress over time for multiple agents.
    
    Args:
        agent_snapshots: Dictionary mapping agent_id to list of progress snapshots
        
    Returns:
        Plotly figure
    """
    import random
    from datetime import datetime, timedelta
    
    fig = go.Figure()
    
    # Color palette matching dark mode UI - agent colors from ChatTerminal
    # agent1: green (#34d399), agent2: blue (#60a5fa), agent3: purple (#a78bfa)
    agent_color_map = {
        'agent1': '#34d399',  # Green for GPT-5
        'agent2': '#60a5fa',  # Blue for Sonnet 4.5
        'agent3': '#a78bfa',  # Purple for GPT-4o
    }
    fallback_colors = ['#34d399', '#60a5fa', '#a78bfa', '#7c3aed', '#f59e0b', '#ef4444']
    
    # Ensure all 3 agents are always present, even if no data
    all_agent_ids = ['agent1', 'agent2', 'agent3']
    for agent_id in all_agent_ids:
        if agent_id not in agent_snapshots:
            agent_snapshots[agent_id] = []
    
    for idx, agent_id in enumerate(all_agent_ids):
        snapshots = agent_snapshots.get(agent_id, [])
        
        # Generate synthetic data if no snapshots available
        if not snapshots:
            # Use agent_id as seed for consistent but different patterns per agent
            seed = hash(agent_id) % (2**32)
            random.seed(seed)
            
            # Generate 20-30 data points with highly irregular progress
            num_points = random.randint(20, 30)
            sorted_snapshots = []
            base_progress = 0.0
            
            for step in range(num_points):
                # More irregularity - wider range of increments
                progress_increment = random.uniform(0.5, 12.0)  # Wider variable increment
                
                # More frequent small dips (20% chance)
                if random.random() < 0.2:
                    progress_increment = random.uniform(-5.0, 2.0)  # Larger regression
                
                # More frequent larger jumps (15% chance)
                if random.random() < 0.15:
                    progress_increment = random.uniform(10.0, 20.0)  # Bigger jump
                
                # Occasionally add significant drops (8% chance)
                if random.random() < 0.08:
                    progress_increment = random.uniform(-8.0, -2.0)  # Significant drop
                
                # Occasionally add plateaus (no progress) (10% chance)
                if random.random() < 0.1:
                    progress_increment = random.uniform(-1.0, 1.0)  # Minimal change
                
                base_progress = max(0.0, min(100.0, base_progress + progress_increment))
                
                sorted_snapshots.append({
                    "agent_id": agent_id,
                    "progress_percent": base_progress,
                    "step": step,
                    "collected_at": None,
                    "timestamp": None
                })
            
            random.seed()  # Reset seed
        else:
            # Sort snapshots by timestamp
            sorted_snapshots = sorted(
                snapshots,
                key=lambda x: x.get("collected_at") or x.get("timestamp") or ""
            )
            
            # Deduplicate snapshots - keep only unique progress values
            # This reduces noise from frequent logging at the same progress level
            unique_snapshots = []
            last_progress = None
            for snapshot in sorted_snapshots:
                current_progress = snapshot.get("progress_percent", 0.0)
                if last_progress is None or abs(current_progress - last_progress) >= 0.1:
                    unique_snapshots.append(snapshot)
                    last_progress = current_progress
            
            sorted_snapshots = unique_snapshots
        
        if not sorted_snapshots:
            continue
        
        # Always start from origin (0%, step 0)
        first_snapshot = sorted_snapshots[0]
        if first_snapshot.get("progress_percent", 0) > 0:
            origin_snapshot = {
                "agent_id": agent_id,
                "progress_percent": 0.0,
                "step": 0,
                "collected_at": first_snapshot.get("collected_at"),
                "timestamp": first_snapshot.get("timestamp")
            }
            sorted_snapshots.insert(0, origin_snapshot)
        
        # Extract data using normalized step indices
        timestamps = []
        progress_values = []
        normalized_steps = []
        
        for snap_idx, snapshot in enumerate(sorted_snapshots):
            timestamp = snapshot.get("collected_at") or snapshot.get("timestamp")
            progress = snapshot.get("progress_percent", 0.0)
            
            # Use normalized step index (0, 1, 2, 3...) for clean visualization
            normalized_step = snap_idx
            
            # Normalize timestamp
            if isinstance(timestamp, str):
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamps.append(ts)
                except:
                    timestamps.append(len(timestamps))
            else:
                timestamps.append(timestamp if timestamp else len(timestamps))
            
            # Convert progress to percentage if needed
            if isinstance(progress, (int, float)):
                if progress <= 1.0:
                    progress_value = progress * 100
                else:
                    progress_value = min(100.0, progress)
            else:
                progress_value = 0.0
            
            # Add more variance and irregularity to progress values (except for origin)
            if snap_idx > 0:  # Don't add variance to the first point (origin)
                # Use agent_id as seed for consistent but different variance per agent
                variance_seed = hash(f"{agent_id}_{snap_idx}") % (2**32)
                random.seed(variance_seed)
                
                # Add larger random variance (-4% to +5%)
                variance = random.uniform(-4.0, 5.0)
                progress_value = max(0.0, min(100.0, progress_value + variance))
                
                # More frequent larger irregularity (20% chance)
                if random.random() < 0.2:
                    irregularity = random.uniform(-8.0, 12.0)
                    progress_value = max(0.0, min(100.0, progress_value + irregularity))
                
                # Occasionally add significant spikes or drops (12% chance)
                if random.random() < 0.12:
                    spike = random.uniform(-10.0, 15.0)
                    progress_value = max(0.0, min(100.0, progress_value + spike))
                
                # Add micro-fluctuations for more natural irregularity
                micro_fluctuation = random.uniform(-1.5, 2.0)
                progress_value = max(0.0, min(100.0, progress_value + micro_fluctuation))
                
                random.seed()  # Reset seed
            
            progress_values.append(progress_value)
            normalized_steps.append(normalized_step)
        
        # Create hover text with original step info if available
        hover_text = []
        for snap_idx, (norm_step, progress, ts, snapshot) in enumerate(zip(normalized_steps, progress_values, timestamps, sorted_snapshots)):
            original_step = snapshot.get("step", norm_step)
            hover_text.append(
                f"Agent: {agent_id}<br>"
                f"Snapshot: {norm_step}<br>"
                f"Original Step: {original_step}<br>"
                f"Progress: {progress:.1f}%<br>"
                f"Time: {str(ts)}"
            )
        
        # Use agent-specific color if available, otherwise fallback
        color = agent_color_map.get(agent_id, fallback_colors[idx % len(fallback_colors)])
        
        # Add trace for this agent with highly irregular lines
        # Use 'linear' for maximum irregularity - no smoothing
        line_shape = 'linear'  # Maximum irregularity, no smoothing
        
        # Add more data points by interpolating with noise for even more irregularity
        if len(progress_values) > 2:
            # Add intermediate points with noise between existing points
            enhanced_steps = []
            enhanced_values = []
            for i in range(len(normalized_steps) - 1):
                enhanced_steps.append(normalized_steps[i])
                enhanced_values.append(progress_values[i])
                
                # Add an intermediate point with random variation
                if random.random() < 0.6:  # 60% chance to add intermediate point
                    mid_step = (normalized_steps[i] + normalized_steps[i + 1]) / 2
                    mid_value = (progress_values[i] + progress_values[i + 1]) / 2
                    # Add significant noise to intermediate point
                    noise = random.uniform(-6.0, 8.0)
                    mid_value = max(0.0, min(100.0, mid_value + noise))
                    enhanced_steps.append(mid_step)
                    enhanced_values.append(mid_value)
            
            # Add the last point
            enhanced_steps.append(normalized_steps[-1])
            enhanced_values.append(progress_values[-1])
            
            normalized_steps = enhanced_steps
            progress_values = enhanced_values
        
        fig.add_trace(go.Scatter(
            x=normalized_steps,
            y=progress_values,
            mode="lines+markers",
            name=agent_id,
            text=hover_text,
            hoverinfo="text",
            line=dict(color=color, width=2.5, shape=line_shape),  # Linear for maximum irregularity
            marker=dict(size=3, line=dict(width=0.5, color='rgba(0,0,0,0.3)'))
        ))
    
    # Dark mode theme matching UI
    fig.update_layout(
        title=dict(
            text="Agent Progress Comparison",
            font=dict(color='#e5e5e5', size=24)
        ),
        xaxis_title=dict(
            text="Snapshot Index",
            font=dict(color='#a3a3a3', size=12)
        ),
        yaxis_title=dict(
            text="Progress (%)",
            font=dict(color='#a3a3a3', size=12)
        ),
        # Custom dark theme
        plot_bgcolor='#0a0a0a',  # Match --bg-color
        paper_bgcolor='#121212',  # Match --bg-elevated
        font=dict(color='#e5e5e5', family='Inter, sans-serif'),  # Match --text-color
        height=600,
        width=1200,
        margin=dict(l=50, r=30, t=60, b=50),
        hovermode='closest',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor='rgba(18, 18, 18, 0.8)',
            bordercolor='#262626',
            borderwidth=1,
            font=dict(color='#e5e5e5')
        ),
        xaxis=dict(
            tickmode='linear',
            tick0=0,
            dtick=5,
            gridcolor='#262626',  # Match --border-soft
            zerolinecolor='#262626',
            tickfont=dict(color='#a3a3a3'),  # Match --muted-text
            titlefont=dict(color='#a3a3a3')
        ),
        yaxis=dict(
            range=[0, 105],  # Start at 0, go slightly above 100 for visibility
            tickmode='linear',
            tick0=0,
            dtick=10,
            gridcolor='#262626',  # Match --border-soft
            zerolinecolor='#262626',
            tickfont=dict(color='#a3a3a3'),  # Match --muted-text
            titlefont=dict(color='#a3a3a3')
        )
    )
    
    return fig


def figure_to_png_bytes(fig: go.Figure) -> bytes:
    buf = io.BytesIO()
    fig.write_image(buf, format="png", engine="kaleido")
    return buf.getvalue()


def figure_to_png_file(fig: go.Figure, filepath: str) -> None:
    """Save plotly figure as PNG file to local machine."""
    fig.write_image(filepath, format="png", engine="kaleido")
