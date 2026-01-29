
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def compute_cdf_values(series):
    """Returns sorted values and their CDF probabilities (i/N)."""
    return np.sort(series), np.arange(1, len(series) + 1) / len(series)

def fs_current_method(candidate_series, long_term_series):
    """Current method using linear interpolation."""
    cand_vals, cand_cdf = compute_cdf_values(candidate_series)
    lt_vals, lt_cdf = compute_cdf_values(long_term_series)
    
    # Interpolate LT CDF at Candidate values
    interp_lt_cdf = np.interp(cand_vals, lt_vals, lt_cdf, left=0, right=1)
    
    N = len(candidate_series)
    fs = np.sum(np.abs(cand_cdf - interp_lt_cdf)) / N
    return fs

def fs_step_function_method(candidate_series, long_term_series):
    """FS using strict step function for LT CDF (no interpolation)."""
    cand_vals, cand_cdf = compute_cdf_values(candidate_series)
    
    # Calculate exact fraction of LT values <= cand_val
    lt_values = np.sort(long_term_series)
    lt_n = len(lt_values)
    
    fs_sum = 0
    N = len(candidate_series)
    
    for i in range(N):
        x = cand_vals[i]
        cand_p = cand_cdf[i] # i/N
        
        # Fraction of LT <= x
        # searchsorted returns index where x should be inserted to maintain order. 
        # 'right': indices s.t. a[i] <= v < a[i+1]. 
        # If v is present, returns index after last occurrence.
        # This corresponds to count(<= x).
        count_le = np.searchsorted(lt_values, x, side='right')
        lt_p = count_le / lt_n
        
        diff = abs(cand_p - lt_p)
        fs_sum += diff
        
    return fs_sum / N

def fs_step_hazen(candidate_series, long_term_series):
    """FS using Hazen plotting position (i - 0.5)/N."""
    N = len(candidate_series)
    cand_vals = np.sort(candidate_series)
    cand_cdf = (np.arange(1, N + 1) - 0.5) / N
    
    lt_values = np.sort(long_term_series)
    lt_n = len(lt_values)
    
    fs_sum = 0
    for i in range(N):
        x = cand_vals[i]
        # LT CDF using Hazen? Or standard? Usually standard step for reference.
        # Let's try standard step for LT.
        count_le = np.searchsorted(lt_values, x, side='right')
        lt_p = count_le / lt_n
        
        diff = abs(cand_cdf[i] - lt_p)
        fs_sum += diff
    return fs_sum / N

# Load Data
print("Loading data...")
file_path = r'D:\Python\pyweatherfiles\SEVILLA.xlsx'
df = pd.read_excel(file_path)

# Rename to standard
df.columns = df.columns.str.strip()
print(f"Columns: {df.columns.tolist()}")

# Map columns
mapping = {
    'fecha': 'time',
    'Dry-bulb temperature_mean': 'T_air_mean'
}
df = df.rename(columns=mapping)

if 'T_air_mean' not in df.columns:
    print("Error: T_air_mean not found after renaming.")
    print(df.columns)
    exit()

df['time'] = pd.to_datetime(df['time'])
df.set_index('time', inplace=True)

# Filter January
df_jan = df[df.index.month == 1]

# Long Term (All Januaries)
lt_series = df_jan['T_air_mean'].dropna()

# Candidate (Jan 2018)
cand_series = df_jan[df_jan.index.year == 2018]['T_air_mean'].dropna()

print(f"Long Term Count: {len(lt_series)}")
print(f"Candidate Count: {len(cand_series)}")

# Calculate FS
fs_curr = fs_current_method(cand_series, lt_series)
fs_step = fs_step_function_method(cand_series, lt_series)
def calculate_fs_general(cand_series, lt_series, cand_pp_method, lt_cdf_method):
    """
    Generic FS calculator.
    cand_pp_method: function(N) -> array of probabilities
    lt_cdf_method: 'interp_linear' or 'step_search'
    """
    cand_vals = np.sort(cand_series)
    N = len(cand_vals)
    cand_probs = cand_pp_method(N)
    
    lt_vals = np.sort(lt_series)
    M = len(lt_vals)
    
    if lt_cdf_method == 'interp_linear':
        # LT CDF is defined by plotting positions too?
        # Usually LT CDF is dense, so we define it at observed points.
        # If we interpolate, we need y-values for LT.
        # Let's assume LT uses same PP method as Candidate? Or standard i/N?
        # Standard Linear Interpolation usually assumes points (x_i, y_i).
        # What are y_i for LT? Standard (i/M) or (i-0.5)/M?
        
        # Taking a guess: Safae might be using the same plotting position for LT.
        lt_probs = cand_pp_method(M)
        interp_lt = np.interp(cand_vals, lt_vals, lt_probs, left=0, right=1)
        
    elif lt_cdf_method == 'step_search':
        # LT CDF is step function count_le / M
        interp_lt = np.zeros(N)
        for i in range(N):
            count_le = np.searchsorted(lt_vals, cand_vals[i], side='right')
            interp_lt[i] = count_le / M
            
    diff = np.abs(cand_probs - interp_lt)
    return np.mean(diff)

# Plotting Position Functions
def pp_california(N): return np.arange(1, N + 1) / N
def pp_hazen(N): return (np.arange(1, N + 1) - 0.5) / N
def pp_weibull(N): return np.arange(1, N + 1) / (N + 1)
def pp_blom(N): return (np.arange(1, N + 1) - 0.375) / (N + 0.25)
def pp_cunnane(N): return (np.arange(1, N + 1) - 0.4) / (N + 0.2)
def pp_gringorten(N): return (np.arange(1, N + 1) - 0.44) / (N + 0.12)


print("-" * 30)
results = [
    f"User's Result (from file): 0.044641",
    f"Safae's Result (from file): 0.034990",
    "-" * 30,
]

methods = {
    'California': pp_california,
    'Hazen': pp_hazen,
    'Weibull': pp_weibull,
    'Blom': pp_blom,
    'Cunnane': pp_cunnane,
    'Gringorten': pp_gringorten
}

for name, func in methods.items():
    # Test with Linear Interpolation for LT (assuming LT uses SAME PP)
    fs1 = calculate_fs_general(cand_series, lt_series, func, 'interp_linear')
    results.append(f"FS {name:12} (LT Interp): {fs1:.6f}")
    
    # Test with Step Search for LT
    fs2 = calculate_fs_general(cand_series, lt_series, func, 'step_search')
    results.append(f"FS {name:12} (LT Step):   {fs2:.6f}")

    # Test Mixed: Candidate uses PP, LT uses California (Standard)
    # This is what fs_step_hazen did earlier (Hazen for Cand, Step/California for LT)
    fs3 = 0
    # Manual mixed
    cand_vals = np.sort(cand_series)
    N = len(cand_vals)
    cand_probs = func(N) # e.g. Hazen
    
    lt_vals = np.sort(lt_series)
    M = len(lt_vals)
    
    # CASE 3: LT is interpolated using California (standard 1/M...1)
    lt_probs_std = np.arange(1, M+1)/M
    interp_lt_std = np.interp(cand_vals, lt_vals, lt_probs_std, left=0, right=1)
    fs3 = np.mean(np.abs(cand_probs - interp_lt_std))
    results.append(f"FS {name:12} (LT StdInt): {fs3:.6f}")
    
    results.append("-" * 10)

for line in results:
    print(line)

with open('summary.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))

# Generate Plot
plt.figure(figsize=(10, 6))

cand_sorted = np.sort(cand_series)
N = len(cand_sorted)

# California (User)
y_cal = np.arange(1, N + 1) / N
plt.step(cand_sorted, y_cal, where='post', label='User (California) i/N', linestyle='-', color='blue')
plt.plot(cand_sorted, y_cal, 'o', color='blue', alpha=0.5)

# Hazen (Safae)
y_hazen = (np.arange(1, N + 1) - 0.5) / N
plt.step(cand_sorted, y_hazen, where='mid', label='Safae (Hazen) (i-0.5)/N', linestyle='--', color='red')
plt.plot(cand_sorted, y_hazen, 'x', color='red', alpha=0.5)

plt.title('CDF Comparison: User (California) vs Safae (Hazen)\nSevilla Jan 2018 Mean Temp')
plt.xlabel('Temperature (C)')
plt.ylabel('Cumulative Probability')
plt.legend()
plt.grid(True)
plt.savefig('fs_comparison.png')
print("Plot saved to fs_comparison.png")

