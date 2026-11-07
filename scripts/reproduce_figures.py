from pathlib import Path
import argparse
import json
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from profile_nesting_release.verify import verify

BLUE = '#256a9b'
ORANGE = '#c97835'
GRAY = '#617080'


def save(figure, name, output, records):
    figure.canvas.draw()
    bounds = [list(axis.get_position().bounds) for axis in figure.axes]
    if len(bounds) > 1:
        height_pt = figure.get_size_inches()[1] * 72
        for component in (1, 3):
            if (max(bound[component] for bound in bounds) - min(bound[component] for bound in bounds)) * height_pt > 1.5:
                raise ValueError('Panel vertical alignment exceeds 1.5 pt.')
    for suffix in ('pdf', 'svg', 'png'):
        figure.savefig(output / (name + '.' + suffix), dpi=300)
    records[name] = {'size_inches': list(figure.get_size_inches()), 'axes_bounds': bounds,
                     'alignment': 'PASS' if len(bounds) > 1 else 'NOT_APPLICABLE'}
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description='Regenerate four quantitative manuscript figures from archived source CSVs; no optimization or new inference.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / 'figures')
    args = parser.parse_args()
    verify()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    data = ROOT / 'data' / 'figure_source'
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Arial', 'DejaVu Sans'],
        'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8.5, 'xtick.labelsize': 7,
        'ytick.labelsize': 7, 'legend.fontsize': 7, 'pdf.fonttype': 42, 'ps.fonttype': 42,
        'svg.fonttype': 'none', 'axes.spines.top': False, 'axes.spines.right': False, 'axes.linewidth': .7})
    records = {}
    paired = pd.read_csv(data / 'multisource_paired_existing.csv')
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 2.8))
    figure.subplots_adjust(left=.085, right=.98, bottom=.23, top=.89, wspace=.35)
    for row in paired.itertuples():
        axes[0].plot([0, 1], [row.ASSIGNMENT_S3, row.ASSIGNMENT_S4], color=GRAY, alpha=.42, linewidth=.7)
    axes[0].scatter(np.zeros(20), paired['ASSIGNMENT_S3'], color=GRAY, s=15, zorder=3)
    axes[0].scatter(np.ones(20), paired['ASSIGNMENT_S4'], color=BLUE, s=15, zorder=3)
    axes[0].set_xticks([0, 1], ['S3\nFixed mappings', 'S4\nTwo-stage joint'])
    axes[0].set_xlim(-.35, 1.35)
    axes[0].set_ylabel('New-purchase weight (t)')
    axes[0].set_title('Paired complete procedures', pad=9)
    differences = paired['difference_s3_minus_s4_t'].to_numpy()
    axes[1].bar(paired['seed'], differences, color=[BLUE if value >= 0 else ORANGE for value in differences], width=.7)
    axes[1].axhline(0, color=GRAY, linewidth=.6)
    axes[1].axhline(.0374, color='#333333', linestyle='--', linewidth=.8, label='Paired median: 0.037400 t')
    axes[1].set_xticks([0, 5, 10, 15, 19])
    axes[1].set_xlabel('Paired seed')
    axes[1].set_ylabel('Procurement difference S3 − S4 (t)')
    axes[1].set_title('17 lower / 2 tied / 1 higher in S4', pad=9)
    axes[1].set_ylim(min(differences) - .015, max(differences) * 1.3)
    axes[1].legend(loc='upper right', frameon=False, fontsize=6.5)
    for label, axis in zip('ab', axes):
        axis.text(-.15, 1.04, label, transform=axis.transAxes, weight='bold', fontsize=10)
    save(figure, 'fig2_paired', output, records)
    purchases = pd.read_csv(data / 'representative_hp160_purchase_by_block.csv')
    summary = purchases.groupby(['scenario', 'stock_material']).agg(length=('purchase_length_m', 'sum'), bars=('purchase_count', 'sum'))
    figure, axis = plt.subplots(figsize=(7.2, 2.7))
    figure.subplots_adjust(left=.14, right=.96, top=.82, bottom=.23)
    left = np.zeros(2)
    for material, color in [('AH32', BLUE), ('AH36', ORANGE)]:
        values = np.array([summary.loc[(scenario, material), 'length'] for scenario in ('S3', 'S4')])
        counts = [int(summary.loc[(scenario, material), 'bars']) for scenario in ('S3', 'S4')]
        axis.barh([1, 0], values, left=left, color=color, height=.5, label=material)
        for index, (value, count) in enumerate(zip(values, counts)):
            axis.text(left[index] + value / 2, 1 - index, f'{value:.3f} m / {count} bars', ha='center', va='center', color='white', fontsize=8)
        left += values
    if not np.allclose(left, [135.5, 133.0]):
        raise ValueError('Representative procurement totals changed.')
    for position, total in zip([1, 0], left):
        axis.text(total + 1.3, position, f'{total:.3f} m\n14 bars', va='center', fontsize=7)
    axis.set_yticks([1, 0], ['S3: fixed\nmappings', 'S4: two-stage\njoint'])
    axis.set_xlim(0, 154)
    axis.set_ylim(-.55, 1.55)
    axis.set_xlabel('New-purchase length for HP 160 × 10 (m)')
    axis.legend(loc='lower left', bbox_to_anchor=(0, 1.05), ncol=2, frameon=False)
    save(figure, 'fig3_purchases', output, records)
    standard = pd.read_csv(data / 'standard_case_medians_existing.csv')
    methods = ['GA', 'ALNS', 'ALNS_MILP' if 'ALNS_MILP' in set(standard['algorithm']) else 'ALNS+MILP']
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    figure.subplots_adjust(left=.085, right=.98, bottom=.27, top=.87, wspace=.35)
    for axis, split, title in zip(axes, ['DEVELOPMENT_VALIDATION', 'HELDOUT'], ['Development/validation: 20 blocks', 'Test split: 7 blocks']):
        selected = standard.loc[standard['split'] == split]
        groups = [selected.loc[selected['algorithm'] == method, 'saved_m'].to_numpy() for method in methods]
        expected = 20 if split == 'DEVELOPMENT_VALIDATION' else 7
        if [len(group) for group in groups] != [expected] * 3:
            raise ValueError('Standard case plot count mismatch.')
        axis.boxplot(groups, positions=np.arange(3), widths=.5, showfliers=False, patch_artist=True,
                     boxprops={'facecolor': '#e3edf3', 'edgecolor': GRAY}, medianprops={'color': BLUE},
                     whiskerprops={'color': GRAY}, capprops={'color': GRAY})
        for index, group in enumerate(groups):
            axis.scatter(index + np.linspace(-.16, .16, len(group)), group, color=BLUE, s=11, alpha=.75, zorder=3)
        axis.axhline(0, color=GRAY, linewidth=.5)
        axis.set_xticks(np.arange(3), ['GA', 'Sequential\nALNS', 'Sequential\nALNS+MILP'])
        axis.set_ylabel('Length saved relative to BFD (m)')
        axis.set_title(title, pad=10)
    for label, axis in zip('ab', axes):
        axis.text(-.15, 1.14, label, transform=axis.transAxes, weight='bold', fontsize=10)
    save(figure, 'figS1_standard', output, records)
    scenario_summary = pd.read_csv(data / 'multisource_summary_existing.csv').set_index('scenario').loc[['S0', 'S1', 'S2', 'S3', 'S4']]
    figure, axes = plt.subplots(1, 3, figsize=(7.2, 2.6))
    figure.subplots_adjust(left=.07, right=.98, bottom=.22, top=.85, wspace=.48)
    for axis, field, title, ylabel in zip(axes,
        ['purchase_weight_t_median', 'waste_length_m_median', 'substitution_penalty_median'],
        ['Procurement', 'Short residual waste', 'Grade substitution'],
        ['New-purchase weight (t)', 'Waste length (m)', 'Penalty (dimensionless)']):
        axis.bar(np.arange(5), scenario_summary[field], color=[GRAY] * 4 + [BLUE], width=.68)
        axis.set_xticks(np.arange(5), scenario_summary.index)
        axis.set_ylabel(ylabel)
        axis.set_title(title, pad=10)
        axis.set_ylim(0, max(scenario_summary[field]) * 1.18)
    for label, axis in zip('abc', axes):
        axis.text(-.2, 1.16, label, transform=axis.transAxes, weight='bold', fontsize=10)
    save(figure, 'figS2_tradeoffs', output, records)
    records['contract'] = {'backend': 'Python/matplotlib', 'minimum_font_pt': 6.5,
        'optimization_runs_added': 0, 'statistical_tests_added': 0,
        'figure_2': 'All 20 paired seeds and archived paired median; no new interval.',
        'figure_3': 'One seed-1 pair; material totals for 14 purchases per solution.',
        'figure_S1': 'All 20 development/validation and seven test case medians per method; no point removal.',
        'figure_S2': 'Archived marginal scenario medians; descriptive resource trade-offs, not paired effect sizes.'}
    (output / 'plot_verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Regenerated four quantitative figures. No optimizer called.')


if __name__ == '__main__':
    main()
