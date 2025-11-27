# Evaluator Metrics Repair - Visual Summary

## Problem Statement

The evaluator metrics were not being displayed in the frontend UI despite being computed in the backend.

### Root Causes Identified

1. **Backend Issue**: The `agent_scores` structure was not including the detailed breakdown metrics (correctness, efficiency, quality, stability, autonomy, resource_efficiency)
   - Problem: Using `report.get("scores", {})` which only had `output_score` and `final_score`
   - Solution: Call `build_score_breakdown()` to generate all 6 metrics

2. **Frontend Issue**: Hard-coded agent list meant new agents or missing data would cause render issues
   - Problem: `['agent1', 'agent2', 'agent3'].map(agentId => ...)` doesn't adapt
   - Solution: Use `Object.entries(agentScores).map(...)` for dynamic rendering

3. **Data Flow Issue**: Metrics were computed but not flowing through to the frontend UI
   - Problem: ScoreBreakdown component expected `breakdown` with 6 keys but got only 2
   - Solution: Ensure breakdown is computed with all required metrics at every stage

## Architecture Diagram

### Before Fix
```
┌─────────────────┐
│  MongoDB Logs   │
└────────┬────────┘
         │
         v
┌─────────────────────────┐
│  DataCollector          │ ✓ Metrics computed here
│  .compute_basic_metrics │
└────────┬────────────────┘
         │
         v
┌──────────────────────┐
│ ScoringEngine        │ ✓ Metrics available
│ .score_task()        │
└────────┬─────────────┘
         │
         v
┌──────────────────────┐
│ ReportBuilder        │ ✓ Metrics included
│ .build_report()      │
└────────┬─────────────┘
         │
         v
┌────────────────────────────┐
│ /status endpoint           │
│ agent_scores[id] = {       │
│   breakdown: {}  ❌ WRONG  │ ← Problem: Only 2 fields
│   metrics: {}    ✓ OK     │
│ }                          │
└────────┬───────────────────┘
         │
         v
┌──────────────────────────────────┐
│ Frontend                         │
│ for agent in ['1','2','3'] {     │ ← Hard-coded
│   breakdown.correctness = ???    │ ← MISSING
│   breakdown.efficiency = ???     │ ← MISSING
│ }                                │
└──────────────────────────────────┘
         ▼
    ❌ BLANK CARDS
```

### After Fix
```
┌─────────────────┐
│  MongoDB Logs   │
└────────┬────────┘
         │
         v
┌─────────────────────────┐
│  DataCollector          │ ✓ Metrics computed
│  .compute_basic_metrics │
└────────┬────────────────┘
         │
         v
┌──────────────────────┐
│ ScoringEngine        │ ✓ Metrics available
│ .score_task()        │
└────────┬─────────────┘
         │
         v
┌──────────────────────┐
│ ReportBuilder        │ ✓ Metrics included
│ .build_report()      │
└────────┬─────────────┘
         │
         v
┌────────────────────────────────────────┐
│ /status endpoint                       │
│ breakdown = build_score_breakdown()    │ ← FIX 1: Call breakdown builder
│ agent_scores[id] = {                   │
│   breakdown: {                         │
│     correctness: 0.92,      ✓ NEW     │
│     efficiency: 0.85,       ✓ NEW     │
│     quality: 0.88,          ✓ NEW     │
│     stability: 0.80,        ✓ NEW     │
│     autonomy: 0.75,         ✓ NEW     │
│     resource_efficiency: 0.90 ✓ NEW   │
│   },                                   │
│   metrics: {completion_time_s, ...}    │
│ }                                      │
└────────┬─────────────────────────────────┘
         │
         v
┌──────────────────────────────────────────┐
│ Frontend                                 │
│ for agent in Object.keys(agentScores) {  │ ← FIX 2: Dynamic agent list
│   const breakdown = data.breakdown       │
│   if (breakdown.correctness) render...   │ ← All 6 metrics available
│ }                                        │
└──────────────────────────────────────────┘
         ▼
    ✓ METRICS DISPLAYED
```

## Key Changes

### Change 1: Backend - evaluator_api.py (lines 107-125)

```python
# OLD CODE
agent_scores[agent_id] = {
    "score": round(final_score, 2),
    "task_id": task_id,
    "evaluated_at": report.get("evaluated_at"),
    "breakdown": report.get("scores", {}),        # ❌ Only {output_score, final_score}
    "metrics": report.get("metrics", {}),         # metrics present but not used
    "penalties": report.get("penalties", {}),
    "summary": report.get("evaluation_summary", ""),
    "is_completed": is_completed
}

# NEW CODE
# Build detailed breakdown with all 6 metrics
report_scores = report.get("scores", {})
report_metrics = report.get("metrics", {})
breakdown = build_score_breakdown(report_scores, report_metrics, is_completed)

agent_scores[agent_id] = {
    "score": round(final_score, 2),
    "task_id": task_id,
    "evaluated_at": report.get("evaluated_at"),
    "breakdown": breakdown,                        # ✓ {correctness, efficiency, quality, stability, autonomy, resource_efficiency}
    "metrics": report_metrics,                     # ✓ metrics now properly matched
    "penalties": report.get("penalties", {}),
    "summary": report.get("evaluation_summary", ""),
    "is_completed": is_completed
}
```

### Change 2: Frontend - EvaluatorView.jsx (lines 459-530)

```jsx
// OLD CODE
<div className="card-body">
    {['agent1', 'agent2', 'agent3'].map(agentId => {  // ❌ Hard-coded list
        const data = agentScores[agentId];
        if (!data) {
            return <EmptyCard />;  // ❌ Shows empty cards for missing agents
        }
        return <PerformanceCard data={data} breakdown={data.breakdown} />;
    })}
</div>

// NEW CODE
<div className="card-body">
    {Object.keys(agentScores).length === 0 ? (
        <div className="placeholder-state">
            <p>No agent scores available yet. Waiting for evaluations...</p>
        </div>
    ) : (
        Object.entries(agentScores).map(([agentId, scoreData]) => {  // ✓ Dynamic list
            const feedbackEntry = agentFeedback[agentId];
            const data = feedbackEntry?.performance_details || scoreData;
            
            // ✓ Guards for missing data
            const breakdown = data?.breakdown || {};
            const metrics = data?.metrics || {};
            
            // ✓ Only render if we have actual data
            if (Object.keys(breakdown).length > 0 || Object.keys(metrics).length > 0) {
                return (
                    <PerformanceCard>
                        <ScoreBreakdown 
                            scores={breakdown}
                            metrics={metrics}
                            penalties={data?.penalties}
                            summary={data?.summary}
                        />
                    </PerformanceCard>
                );
            } else {
                return (
                    <div style={{padding: '12px', color: 'var(--muted-text)'}}>
                        <p>Metrics not yet available. Processing...</p>
                    </div>
                );
            }
        })
    )}
</div>
```

## Data Structure Comparison

### Backend Response Structure

#### Before Fix
```json
{
  "agent_scores": {
    "agent1": {
      "score": 85.5,
      "breakdown": {
        "output_score": 92,
        "final_score": 0.855
      },
      "metrics": {
        "completion_time_s": 45.3,
        "error_count": 2,
        "total_api_calls": 15,
        "cost_usd": 0.08
      }
    }
  }
}
```

#### After Fix
```json
{
  "agent_scores": {
    "agent1": {
      "score": 85.5,
      "breakdown": {
        "correctness": 0.92,
        "efficiency": 0.85,
        "quality": 0.88,
        "stability": 0.80,
        "autonomy": 0.75,
        "resource_efficiency": 0.90
      },
      "metrics": {
        "completion_time_s": 45.3,
        "error_count": 2,
        "total_api_calls": 15,
        "cost_usd": 0.08,
        "retry_count": 1,
        "memory_usage_mb": 256.5,
        "cpu_usage_percent": 42.5,
        "human_or_agent_requests": 3
      }
    }
  }
}
```

## Frontend UI Improvements

### Before Fix
```
┌─────────────────────────────┐
│ Performance by Agent        │
├─────────────────────────────┤
│ Agent 1 - GPT4    [?] 0%   │ ← No data
├─────────────────────────────┤
│ Agent 2 - GPT 5   [?] 0%   │ ← No data
├─────────────────────────────┤
│ Agent 3 - GPT 4.1 [?] 0%   │ ← No data
└─────────────────────────────┘
```

### After Fix
```
┌─────────────────────────────────┐
│ Performance by Agent            │
├─────────────────────────────────┤
│ Agent 1 - GPT4        85.5% ▼   │ ← Real data
│ █████████████░░░░░░░░░░░░░░    │
│                                 │
│ ┌─────────────────────────────┐ │
│ │ Score Breakdown             │ │
│ │ Correctness   ██████████ 92%│ │
│ │ Efficiency    ████████░░ 85%│ │
│ │ Quality       █████████░ 88%│ │
│ │ Stability     ████████░░ 80%│ │
│ │ Autonomy      ███████░░░ 75%│ │
│ │ Resource Eff  █████████░ 90%│ │
│ │                             │ │
│ │ Raw Metrics                 │ │
│ │ Time: 45.3s  Errors: 2      │ │
│ │ API Calls: 15  Cost: $0.08  │ │
│ └─────────────────────────────┘ │
├─────────────────────────────────┤
│ Agent 2 - GPT 5       72.0% ▼   │ ← Real data
│ ████████░░░░░░░░░░░░░░░░░░░    │
├─────────────────────────────────┤
│ Agent 3 - GPT 4.1     91.3% ▼   │ ← Real data
│ ██████████░░░░░░░░░░░░░░░░░    │
└─────────────────────────────────┘
```

## Testing Strategy

### 1. Backend Validation
```bash
# Check if breakdown is being computed
curl http://localhost:8000/status | jq '.agent_scores | to_entries[0].value.breakdown'

# Expected output:
# {
#   "correctness": 0.92,
#   "efficiency": 0.85,
#   ...
# }
```

### 2. Frontend Validation
```javascript
// In browser DevTools console
const response = await fetch('/evaluator/status');
const data = await response.json();
console.log(data.agent_scores);

// Should show multiple agents with proper breakdown structure
```

### 3. UI Validation
- [ ] Performance cards show non-zero percentages
- [ ] Clicking card expands to show all 6 metrics
- [ ] Raw metrics section displays time, errors, API calls, cost
- [ ] No console errors
- [ ] Works with any agent ID, not just agent1/2/3

## Impact Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Backend Structure** | Incomplete breakdown | Complete with all 6 metrics |
| **Frontend List** | Hard-coded [1,2,3] | Dynamic from response |
| **Missing Data** | Shows empty cards | Shows placeholder text |
| **Metrics Visible** | ❌ No | ✓ Yes |
| **Adaptability** | ❌ Fixed | ✓ Flexible |
| **Error Handling** | ❌ Poor | ✓ Good |
| **Performance** | ✓ Good | ✓ Same |

## Verification Checklist

- [ ] Backend computes breakdown with all 6 metrics
- [ ] Frontend iterates over actual agent IDs
- [ ] ScoreBreakdown component receives all required data
- [ ] Metrics render with proper percentages and bars
- [ ] No console errors or warnings
- [ ] UI adapts when agent list changes
- [ ] Placeholder shown when metrics not available
- [ ] Performance remains acceptable
