# Load libraries
import time
import numpy as np
import pandas as pd
import multiprocessing
import jax
import jax.numpy as jnp
from jax import random, vmap, jit
import src.Aux_functions as aux

# parameters guides:
# theta: p(A* | X, theta)
# gamma: p(A | A*, X, gamma)
# eta, sig_y: p(Y | Z, X, A*, eta, sig_y)
# alpha: pi_alpha(z) ---> stochastic intervention

def one_simuation_iter(idx, theta, gamma, eta, sig_y, pz, n_rep, lin_y, alphas):
    rng_key = random.PRNGKey(1)
    _, rng_key = random.split(rng_key)

    rng = np.random.default_rng(idx)

    # --- Get data ---
    df_oracle = aux.DataGeneration(rng=rng, theta=theta, eta=eta, sig_y=sig_y, pz=pz, lin=lin_y, alphas=alphas).get_data()
    print("Median true Zeigen = ", jnp.median(df_oracle["Zeigen"]))
    # Generate noisy network measurement
    # obs_network = aux.create_noisy_network(df_oracle["adj_mat"], gamma)
    # obs_network = aux.create_noisy_network(df_oracle["triu"], gamma, df_oracle["X2_equal"])
    obs_network = aux.create_noisy_network(rng, df_oracle["triu"], gamma, df_oracle["X_diff"], df_oracle["X2_equal"])
    # save observed df and update A* and triu
    df_obs = df_oracle.copy()
    df_obs["adj_mat"] = obs_network["obs_mat"]
    df_obs["triu"] = obs_network["triu_obs"]

    trils_pd = pd.DataFrame({'true': df_oracle["triu"], 'obs': df_obs["triu"]})
    print(pd.crosstab(index=trils_pd['true'], columns=trils_pd['obs']))

    # print("Running network module")
    # --- network module ---
    # network_mcmc = aux.Network_MCMC(data=df_obs, rng_key=rng_key)
    # network_svi = aux.Network_SVI(data=df_obs, rng_key=rng_key, n_iter=600, n_samples=250)
    network_svi = aux.Network_SVI(data=df_obs, rng_key=rng_key, n_iter=20000, n_samples=10000)
    # network_svi = aux.Network_SVI(data=df_obs, rng_key=rng_key, n_iter=100, n_samples=30)
    network_svi.train_model()
    # get posterior samples and predictive distributions
    # network_post = network_mcmc.get_posterior_samples()
    # network_mean_post = network_mcmc.mean_posterior()
    # print("getting network posterior samples")
    # network_pred_samples = network_mcmc.predictive_samples()
    network_pred_samples = network_svi.network_samples()

    # print("Running obs and oracle outcome modules")
    # --- Outcome module (linear & GP) ---
    # with true network
    print("Running Oracle")
    oracle_outcome_mcmc = aux.Outcome_MCMC(data=df_oracle, type="oracle", rng_key=rng_key, iter=idx)
    oracle_results = oracle_outcome_mcmc.get_results()
    # with observed network
    print("Running Observed")
    obs_outcome_mcmc = aux.Outcome_MCMC(data=df_obs, type="observed", rng_key=rng_key, iter=idx)
    obs_results = obs_outcome_mcmc.get_results()

    #  --- cut-posterior ---
    # print("Running TWOSTAGE")
    # # Two-Stage
    # twostage_multi_nets = aux.get_many_post_astars(n_rep, network_mean_post, df_obs["X_diff"], df_obs["triu"])
    # twostage_results = aux.multistage_run(multi_samp_nets=twostage_multi_nets,
    #                                         Y=df_obs["Y"],
    #                                         Z_obs=df_obs["Z"],
    #                                         Z_h=df_obs["Z_h"],
    #                                         Z_stoch=df_obs["Z_stoch"],
    #                                         X=df_obs["X"],
    #                                         X2=df_obs["X2"],
    #                                         K=n_rep,
    #                                         iter=idx,
    #                                         h_estimand=df_obs["estimand_h"],
    #                                         stoch_estimand=df_obs["estimand_stoch"],
    #                                         key=rng_key_)

    # Get posterior network stats
    post_zeig, post_zeig_h1, post_zeig_h2, post_zeig_stoch1, post_zeig_stoch2 = aux.get_post_net_stats(network_pred_samples,
                                                                                                       df_obs["Z"],
                                                                                                       df_obs["Z_h"],
                                                                                                       df_obs["Z_stoch"])

    # print("Post abs zeigen estimator error:", np.mean(np.abs(np.mean(post_zeig,axis=0) - df_oracle["Zeigen"])))
    post_zeig_error = np.mean(np.abs(post_zeig - df_oracle["Zeigen"]))
    print("Post abs zeigen error:", post_zeig_error)
    esti_post_zeig_error = jnp.mean(np.abs(post_zeig.mean(axis=0) - df_oracle["Zeigen"]))
    print("Rand post abs zeigen error:", esti_post_zeig_error)

    # TODO: save MAE of posterior observed zeigen values

    print("Running Multistage")
    # Three-Stage
    i_range = np.random.choice(a=range(network_pred_samples.shape[0]), size=n_rep, replace=False)

    # threestage_multi_nets = network_pred_samples[i_range,]
    threestage_results = aux.multistage_run(zeigen_post = post_zeig[i_range,],
                                            zeigen_h1_post = post_zeig_h1[i_range,],
                                            zeigen_h2_post=post_zeig_h2[i_range,],
                                            zeigen_stoch_post = post_zeig_stoch1[i_range,],
                                            zeigen_stoch2_post=post_zeig_stoch2[i_range,],
                                            x=df_obs["X"],
                                            x2=df_obs["X2"],
                                            y=df_obs["Y"],
                                            z_obs=df_obs["Z"],
                                            z_h=df_obs["Z_h"],
                                            z_stoch=df_obs["Z_stoch"],
                                            h_estimand=df_obs["estimand_h"],
                                            stoch_estimand=df_obs["estimand_stoch"],
                                            iter=idx,
                                            key=rng_key)

    # threestage_results = aux.multistage_run(multi_samp_nets=threestage_multi_nets,
    #                                         Y=df_obs["Y"],
    #                                         Z_obs=df_obs["Z"],
    #                                         Z_h=df_obs["Z_h"],
    #                                         Z_stoch=df_obs["Z_stoch"],
    #                                         X=df_obs["X"],
    #                                         X2=df_obs["X2"],
    #                                         B=n_rep,
    #                                         iter=idx,
    #                                         h_estimand=df_obs["estimand_h"],
    #                                         stoch_estimand=df_obs["estimand_stoch"],
    #                                         key=rng_key,
    #                                         true_zeigen = df_oracle["Zeigen"])

    # print("Mean MS zeigen error: ", threestage_results[1])
    # threestage_results = threestage_results[0]
    #
    # print("Running ONESTAGE")
    # # One-Stage
    # # post_zeig, post_zeig_h1, post_zeig_h2, post_zeig_stoch1, post_zeig_stoch2 = aux.get_onestage_stats(network_pred_samples,
    # #                                                                                                    df_obs["Z"],
    # #                                                                                                    df_obs["Z_h"],
    # #                                                                                                    df_obs["Z_stoch"])
    #
    mean_post_zeig = post_zeig.mean(axis=0)
    mean_post_zeigen_h1 = post_zeig_h1.mean(axis=0)
    mean_post_zeigen_h2 = post_zeig_h2.mean(axis=0)
    mean_post_zeigen_stoch1 = post_zeig_stoch1.mean(axis=0)
    mean_post_zeigen_stoch2 = post_zeig_stoch2.mean(axis=0)

    onestage_outcome_mcmc = aux.Onestage_MCMC(Y=df_obs["Y"],
                                              X=df_obs["X"],
                                              X2=df_obs["X2"],
                                              Z_obs=df_obs["Z"],
                                              Z_h=df_obs["Z_h"],
                                              Z_stoch=df_obs["Z_stoch"],
                                              estimand_h=df_obs["estimand_h"],
                                              estimand_stoch=df_obs["estimand_stoch"],
                                              zeigen=mean_post_zeig,
                                              h1_zeigen=mean_post_zeigen_h1,
                                              h2_zeigen=mean_post_zeigen_h2,
                                              stoch1_zeigen=mean_post_zeigen_stoch1,
                                              stoch2_zeigen=mean_post_zeigen_stoch2,
                                              rng_key=rng_key,
                                              iter=idx)
    onestage_results = onestage_outcome_mcmc.get_results()


    results_all = jnp.vstack([oracle_results, obs_results,
                             # twostage_results, threestage_results,
                             threestage_results,
                             onestage_results])

    # results_all = pd.concat([oracle_results, obs_results,
    #                          twostage_h_results, twostage_stoch_results,
    #                          threestage_h_results, threestage_stoch_results,
    #                          onestage_results])
    #
    # results_all.to_csv(w_path + "/" + dgp + "_" + str(idx) + ".csv", index=False)
    return results_all


vectorized_simulations = vmap(one_simuation_iter, in_axes = (0,) + (None,) * 8)

# vectorized_simulations = vmap(run_one_iter, in_axes= (0,) + (None,) * 10)
# vectorized_simulations = vmap(run_one_iter, in_axes=(0,None,None,None,None,None,None,None,None,None,None))

COLUMNS = ["idx", "mean", "median", "true", "bias",
           "std", "RMSE", "RMSE_all", "MAE", "MAE_all",
           "MAPE", 'MAPE_all', 'rel_RMSE', 'rel_RMSE_all',
           # "std", "RMSE", "MAE", "MAPE",
           "q025", "q975", "covering", "mean_ind_cover"]
           # "std", "RMSE", "MAE", "MAPE", "q025", "q975", "covering"]
           # , "hdi_lower", "hdi_upper"]
# COLUMNS = ["idx", "method", "estimand", "mean", "median",
#                     "true", "bias", "std", "RMSE", "q025", "q975", "covering"]

# METHODS = ['Linear_oracle', 'GP_oracle',
#              'Linear_observed', 'GP_observed',
#              # 'Linear_2S', 'GP_2S', 'Linear_2S', 'GP_2S',
#              'Linear_3S', 'GP_3S',
#              # 'Linear_3S', 'GP_3S', 'Linear_3S', 'GP_3S',
#              'Linear_1S', 'GP_1S']
#
# ESTIMANDS = ['dynamic', 'dynamic',
#             'dynamic', 'dynamic',
#             # 'dynamic', 'dynamic', 'stoch', 'stoch',
#             'dynamic', 'dynamic',
#             # 'dynamic', 'dynamic', 'stoch', 'stoch',
#             'dynamic', 'dynamic']

METHODS = ['Linear_oracle', 'GP_oracle', 'Linear_oracle', 'GP_oracle',
             'Linear_observed', 'GP_observed', 'Linear_observed', 'GP_observed',
             # 'Linear_2S', 'GP_2S', 'Linear_2S', 'GP_2S',
             'Linear_3S','Linear_3S', 'GP_3S', 'GP_3S',
             # 'Linear_3S', 'GP_3S', 'Linear_3S', 'GP_3S',
             'Linear_1S', 'GP_1S', 'Linear_1S', 'GP_1S']

ESTIMANDS = ['dynamic', 'dynamic', 'stoch', 'stoch',
            'dynamic', 'dynamic', 'stoch', 'stoch',
            # 'dynamic', 'dynamic', 'stoch', 'stoch',
            'dynamic', 'stoch', 'dynamic', 'stoch',
            # 'dynamic', 'dynamic', 'stoch', 'stoch',
            'dynamic', 'dynamic', 'stoch', 'stoch']

def results_to_pd_df(results, n_iter):
    res_df = jnp.vstack(results)
    combined_df_pd = pd.DataFrame(res_df, columns=COLUMNS)
    # combined_df_pd = pd.DataFrame(results, columns=COLUMNS)
    combined_df_pd["method"] = METHODS*n_iter
    combined_df_pd["estimand"] = ESTIMANDS*n_iter
    return combined_df_pd
