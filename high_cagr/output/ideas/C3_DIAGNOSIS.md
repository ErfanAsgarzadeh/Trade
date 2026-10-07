# C3 diagnosis (10 coins, full period, 4h PULL / TRAILW / NOWKND)
trades 1507, win rate 35.3%, mean net +0.324R, top 10% of trades = 173% of net R

## Losing trades by category
                     n   sum_R  median_bars  share_loss_R
category                                                 
COST_FLIP           10   -0.33         47.5          0.04
FAST_REVERSAL       14  -13.95          1.5          1.69
GIVEBACK_GE1R      281 -164.03         30.0         19.84
NO_FOLLOW_THROUGH  456 -452.40          4.5         54.72
SLOW_FAILURE       214 -196.07         18.5         23.72

## Exit kind
                n    sum_R    win
exit_kind                        
INITIAL_STOP  673  -669.30    0.0
TRAIL_LOSS    302  -157.48    0.0
TRAIL_PROFIT  532  1315.63  100.0

## Winners: how much of the peak is kept
            n  mean_mfe  mean_exit_R  capture
mfe_R                                        
(0, 2]     48      1.57         0.29     0.16
(2, 4]    199      2.89         0.89     0.29
(4, 8]    201      5.63         2.93     0.53
(8, 100]   84     12.36         7.33     0.60

## Big trends (>=30%, >=7 days): share of the move
WITH                         38.4
AGAINST                      20.4
FLAT:trend_filter_against    19.2
FLAT:weekend_blocked          0.1
FLAT:no_signal               17.8

## Long vs short (train=True/False)
               n   sum_R    win
side  train                    
LONG  False  181   26.91  27.62
      True   392  131.54  34.44
SHORT False  346  140.90  37.57
      True   588  189.49  36.90

## TRAIN cohort: adx
             n  mean_R     win
adx                           
(0, 15]     52   0.002  30.769
(15, 20]   186   0.341  37.634
(20, 25]   230   0.392  37.826
(25, 35]   370   0.422  35.135
(35, 100]  142   0.078  34.507

## TRAIN cohort: atr_rel
               n  mean_R     win
atr_rel                         
(0.0, 0.8]   113   0.493  35.398
(0.8, 1.0]   337   0.417  37.982
(1.0, 1.2]   323   0.245  36.533
(1.2, 1.5]   160   0.145  31.875
(1.5, 10.0]   47   0.477  31.915

## TRAIN cohort: ema_gap_atr
               n  mean_R     win
ema_gap_atr                     
(-1, 1]      243   0.226  37.037
(1, 2]       264   0.586  40.530
(2, 4]       302   0.259  31.457
(4, 8]       162   0.164  34.568
(8, 100]       9   0.747  44.444

## TRAIN cohort: dist_ema50_atr
                  n  mean_R     win
dist_ema50_atr                     
(-20, -1]       392   0.150  33.163
(-1, 0]         491   0.495  39.715
(0, 1]           84   0.329  30.952
(1, 2]            6  -0.901   0.000
(2, 20]           7  -0.456  14.286

## TRAIN cohort: rsi_dip
            n  mean_R     win
rsi_dip                      
(0, 25]    99   0.085  28.283
(25, 30]  165   0.085  38.788
(30, 35]  334   0.378  38.323
(35, 40]  382   0.451  34.555

## TRAIN cohort: cross_age_bars
                  n  mean_R     win
cross_age_bars                     
(-1, 30]         69   1.053  46.377
(30, 90]        217   0.388  36.866
(90, 180]       237   0.298  35.443
(180, 400]      327   0.296  35.780
(400, 5000]     130  -0.026  30.000