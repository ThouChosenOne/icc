import query_cell_tower as CellTower
import math

def calc_distance(lat1, lon1, lat2, lon2):
    # approximate radius of earth in km
    R = 6373.0

    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)

    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1

    a = math.sin(dlat / 2)**2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return (R * c) * 1000

def tic(found_list, current_lat=52.2311057, current_lon=6.8553815, range_multiplier=1, verbose=True):
# Tower Information Consistency Check
    if len(found_list) > 0:
        print("Printing cell tower info and checking database....")
        # return {"s_rank" : 0, "detector_name"  : "tic"}
        result = dict()
        for info in sorted(found_list):
            print info
            if verbose:
                print info.get_verbose_info()
            towers = CellTower.queryTower(info.mcc, info.mnc, info.cid)
            if len(towers) > 0:
                tower = towers[0]
                distance = calc_distance(tower.lat, tower.lon, current_lat, current_lon)
                if distance > (tower.range * range_multiplier):
                    print(" Cell tower found in database, but in wrong location %d m (range %d m)"%(distance, tower.range))
                    result.append({'s_rank' : 1, 'detector_name'  : 'tic', 'arfcn': info.arfcn})
                else:
                    result.append({'s_rank' : 0, 'detector_name'  : 'tic', 'arfcn': info.arfcn})
                    print(" Cell tower found in database")
            else:
                result.append({'s_rank' : 2, 'detector_name'  : 'tic', 'arfcn': info.arfcn})
                print(" No match found in database")
    else:
        print("No cell towers found...")
    return result