from pyweatherfiles.tmy import TMYGenerator


COLUMN_MAPPING = {
    'fecha': 'time',
    'Dry-bulb temperature_max': 'T_air_max',
    'Dry-bulb temperature_min': 'T_air_min',
    'Dry-bulb temperature_mean': 'T_air_mean',
    'Dew Point temperature_max': 'T_dew_max',
    'Dew Point temperature_min': 'T_dew_min',
    'Dew Point temperature_mean': 'T_dew_mean',
    'Wind speed_max': 'Wind_speed_max',
    'Wind speed_mean': 'Wind_speed_mean',
    'GHI_sum': 'GHI_sum',
    'DNI_sum': 'DNI_sum',

    'DATETIME_UTC': 'time',
    'Dry-bulb temperature': 'T_air',
    'Dew Point temperature': 'T_dew',
    'Wind speed': 'Wind_speed',
    'BNI/DNI': 'DNI'
}


# city = 'MADRID'
for city in ['MADRID', 'SEVILLA']:
    tmy_gen = TMYGenerator(
        file_path=f'{city}.xlsx',
        cdf_method='daily',
        data_frequency='daily',
        column_mapping=COLUMN_MAPPING,
        weighting_method='tmy3',
        save_validation_dfs=True,
        hourly_file_path=f'{city}_horario.xlsx'
    )

    tmy_gen.generate_tmy(persistence_method='sequential')
    for ext in ['csv', 'xlsx', 'tmy']:
        tmy_gen.export_tmy(output_path=f'{city}_tmy_v03.{ext}')

    tmy_gen.validation_st2_summary_fs_ranking.to_excel(f'{city}_summary_fs_ranking_v03.xlsx')
    tmy_gen.validation_st3_df_persistence_decision.to_excel(f'{city}_persistence_runs_v03.xlsx')
    tmy_gen.validation_st4_df_tmy_composition.to_excel(f'{city}_tmy_composition_v03.xlsx')

    tmy_gen.plot_annual_cdfs(save_figure_data=True)
    tmy_gen.plot_monthly_cdfs(sharex=False, save_figure_data=True)
    tmy_gen.plot_monthly_means(save_figure_data=True)

    keys = [k for k in tmy_gen.figures_data.keys()]
    for k in keys:
        fig = tmy_gen.figures_data[k]['fig']
        fig.savefig(f'{city}_{k}_v03.png')
