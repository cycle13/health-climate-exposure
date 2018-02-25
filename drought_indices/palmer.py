import calendar
from collections import deque
import logging
import math
import numba
import numpy as np
from . import utils
import warnings

# set up a basic, global logger
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s',
                    datefmt='%Y-%m-%d  %H:%M:%S')
logger = logging.getLogger(__name__)


#-----------------------------------------------------------------------------------------------------------------------
_PDSI_MIN = -4.0
_PDSI_MAX = 4.0

#-----------------------------------------------------------------------------------------------------------------------
def print_values(values,
                 title):
    
    print(title)

    # use divmod to determine whether or not we'll have an additional/partial year    
    dmod = divmod(len(values), 12)
    if dmod[1] > 0:
        additional = 1
    else:
        additional = 0
        
    # print each year's values per line
    np.set_printoptions(precision=3)
    for i in range(dmod[0] + additional):
        print(values[i*12:i*12 + 12])
        
#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def pmdi(probability,
         X1, 
         X2, 
         X3):
    
    # the index is near normal and either a dry or wet spell exists, choose the largest absolute value of X1 or X2
    if X3 == 0:
        
        if abs(X2) > abs(X1):
            pmdi = X2
        else:
            pmdi = X1   
    
    else:
        if (probability > 0) and (probability < 100):
    
            PRO = probability / 100.0
            if X3 <= 0:
                # use the weighted sum of X3 and X1
                pmdi = ((1.0 - PRO) * X3) + (PRO * X1)
            
            else:
                # use the weighted sum of X3 and X2
                pmdi = ((1.0 - PRO) * X3) + (PRO * X2)
        else:
            # a weather spell is established
            pmdi = X3

    return pmdi

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def thornthwaite(T_F,
                 latitude_degrees,
                 total_years,
                 fill_value,
                 return_inches=True):
    '''
    :param T_F: the temperature in degrees F, one dimensional Numpy array of floats with size == (total_years x 12)
    :param latitude_degrees: the latitude in degrees north
    :param total_years the total number of years of data contained in the input temperature array
    :param fill_value: value used to represent fill/missing values in the input temperature array
    :param return_inches units for the returned PET values -- either in inches (True/default) or millimeters (False)
    :return: array of monthly PET values corresponding in length to the input temperature array, either in inches (return_inches == True) or
             in millimeters (return_inches == False)
    '''
    
    # The Thornthwaite_PET function calculates the potential evapotranspiration 
    # using Thornthwaite's method (cf. (1) Thornthwaite, Wilm, et al., 1944; 
    # Transactions of the American Geophysical Union, Vol. 25, pp. 683-693; 
    # (2) Thornthwaite, 1948; Geographical Review, Vol. 38, No. 1, January
    # 1948; (3) Thornthwaite and Mather, 1955; Publications in Climatology,
    # Vol. 8, No. 1; and (4) Thornthwaite and Mather, 1957; Publications in 
    # Climatology, Vol. 10, No. 3)
    
    # days_in_month is the number of days in each of the 12 months.
    days_in_month = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    
    # J is the Julian day of the middle of month m. Pre-allocate J for speed.
    J = np.empty(days_in_month.shape)#, dtype=np.int)
    
    for m in range(days_in_month.shape[0]):
        days = days_in_month[m] / 2
        if m == 0:
            J[m] = days
        else:
            J[m] = days + sum(days_in_month[0:m])
    
    ## CONVERT TEMPERATURE FROM DEGREES FAHRENHEIT (F) TO DEGREES CELSIUS (C)
    
    # Haith and Shoemaker (cf. Haith and Shoemaker, 1987; Journal of the 
    # American Water Resources Association; Vol. 23, No. 3, June 1987) set PET
    # equal to zero on days for which the mean monthly temperature is less than
    # or equal to zero. T_C is the temperature record in degrees Celsius where
    # those temperatures that were less than zero are now zero, such that the
    # subsequent calculation of the potential evapotranspiration (PET) renders
    # a PET equal to zero.
    T_C = (T_F - 32) * (5/9)
    T_C[T_C < 0.0] = 0.0
    
    ## CALCULATE THE POTENTIAL EVAPOTRANSPIRATION FOR EACH LOCATION j
    
    # lat_rad is the latitudes in radians
    lat_rad = math.radians(latitude_degrees)
    
    # TLAT is the negative tangent of the latitiude (where the latitude is in radians).
    TLAT = -1.0 * math.tan(lat_rad)
    
    # reshape the temperature values array into (total_years, 12) so rows represent years and columns represent months
    T = np.reshape(T_C, (total_years, 12))
    
    ## CALCULATE VARIABLES USED IN THE PET CALCULATION
    
    # These equations are different than those presented in 
    # the NCDC and CPC PDSI fortran codes. Both the NCDC and CPC use 
    # transformed equations. This code follows Allen et al. (1994a), Allen 
    # et al. (1994b), and Duffle and Beckman (1991).
        # (1) Allen et al., 1994a; "An Update for the Calculation of 
        # Reference Evapotranspiration," ICID Bulletin of the International 
        # Commission on Irrigation and Drainage; 
        # (2) Allen et al., 1994b; "An Update for the Definition of 
        # Reference Evapotranspiration," ICID Bulletin of the International 
        # Commission on Irrigation and Drainage; and
        # (3) Duffie and Beckman, 1974; "Solar  engineering thermal
        # processes," Wiley and Sons, NY. 
        
        
    # Calculate PHI, the solar declination angle on Julian day (J).
    PHI = 0.4093 * np.sin(((2.0 * math.pi / 365.0) * J) - 1.405)
    
    # Calculate w (omega), the sunset hour angle on Julian day (J).
    w = np.arccos(TLAT * PHI)
    
    # Calculate D, the number of daylight hours (day length) on Julian day (J).
    D = 24.0 * w / math.pi
    
    # Calculate DL, the day length normalizer.
    DL = D / 12.0
    
    # Calculate DM, the month length normalizer.
    DM = days_in_month / 30
    
    # Calculate h, the heat index for for month m of year y.
    h = np.power((T / 5), 1.514)

    # Calculate H, the yearly heat index for all years of the temperature record.
    H = np.sum(h, axis=1)
    
    # Calculate a, the PET exponent for year y.
    a = ((6.75 * pow(10, -7) * np.power(H, 3) - (7.71 * pow(10, -5)) * np.power(H, 2) + (1.792 * pow(10, -2)) * H + 0.49239))

    ## CALCULATE PET FOR EACH MONTH OF EACH YEAR FOR LOCATION j 
    
    # These equations are different than those presented in 
    # the NCDC and CPC PDSI fortran codes. Both the NCDC and CPC use 
    # transformed equations (see Hobbins et al., 2008; Geophysical 
    # Research Letters, Vol. 23, L12403, doi:10.1029/2008GL033840; and  
    # Dai, 2011; Journal of Geophysical Research, Vol. 116, D12115, 
    # doi:10.1029/2010JD015541). 
    
    # These equations do not match the CPC and NCDC transformed equations,  
    # but instead follow Thornthwaite's untransformed equations.
        # (1) Thornthwaite's initial proposal of the method: Wilm, et al., 
        # 1944; Transactions of the American Geophysical Union, Vol. 25, 
        # pp. 683-693; 
        # (2) Comprehensive methodology, PET calculations by temperature: 
        # Thornthwaite, 1948; Geographical Review, Vol. 38, No. 1, January 
        # 1948; 
        # (3) Modifications and instructions: Thornthwaite and Mather, 
        # 1955; Publications in Climatology, Vol. 8, No. 1; 
        # (4) Modifications and instructions: Thornthwaite and Mather, 
        # 1957; Publications in Climatology, Vol. 10, No. 3; and
        # (5) Detailed Methodology: Thornthwaite and Havens, April 1958; 
        # Monthly Weather Review. 
    # Thornthwaite's method for calculating the PET is used here (as 
    # opposed to the Penman-Monteith or Hamon methods). Nevertheless, PDSI
    # values should be insensitive to alternative methods (van der Schrier,
    # 2011). 
        # (1) G. van der Schrier et al., 2011; Journal of Geophysical 
        # Research, Vol. 116, D03106, doi:10.1029/2010JD015001
    # The PET is calculated here according to three temperature ranges: T
    # < 0C, 0C <= T < 26.5C, and T >= 26.5C (Thornthwaite, 1948; Willmott 
    # et al., 1985; Haith and Shoemaker, 1987).
        # (1) Willmott et al., 1985; Journal of Climatology, Vol 5, pp
        # 589-606; and
        # (2) Haith and Shoemaker, 1987; Journal of the 
        # American Water Resources Association; Vol. 23, No. 3, June 1987.
    
    # PET_mm is the potential evapotranspiration array we'll compute, in millimeters
    PET_mm = np.empty(T.shape)
    
    for y in range(total_years):   # y is the counter for each year of the data
        for m in range(12):        # m is the counter for each of the 12 calendar months
            
            # account for months with missing/fill values (for example the final pad months in the final year where we have fill values)
            if T[y, m] == fill_value:
                continue
            
            # for temperatures <= 32 degrees F we can't compute PET (no evaporation of frozen water)
            elif T[y, m] <= 0.0:
                PET_mm[y, m] = 0.0
                
            # calculate PET for temperatures between 32 and 80 degrees F (26.5 C == 80 F)
            elif (T[y, m] > 0.0) and (T[y, m] < 26.5):
                PET_mm[y, m] = 16 * DL[m] * DM[m] * np.power(((10.0 * T[y, m]) / H[y]), a[y])
            
            # calculate PET for temperatures 80 degrees F and above (26.5 C == 80 F)
            elif T[y, m] >= 26.5:
                PET_mm[y, m] = (-415.85 + 32.24 * T[y, m] - 0.43 * (np.power(T[y, m], 2))) * DL[m] * DM[m]
    
    # convert PET from millimeters to inches, if required
    PET_final = PET_mm
    if return_inches == True:
        PET_final = PET_mm / 25.4    # 1 inch == 25.4 mm
        
    return PET_final

# 
#                       
#     ## NCDC PET Calculation ##
#     #{
#     #
#     # If you would like to run the code using the NCDC equation for PDSI,
#     # please comment out lines 81-192 and uncomment lines 195-260.
#     #
#     #
#     load NCDC_soilcnst.txt; # Loads the text file that contains the NCDC
#                             # constants used to calculate PET. 
#     B = NCDC_soilcnst(:,3); # B is the NCDC equivalent of a, Thornthwaite's
#                             # PET exponent; instead of a yearly exponent, 
#                             # only one exponent is used for all years.
#     h = NCDC_soilcnst(:,4); # Instead of a yearly heat index, only one heat
#                             # index is used for all years.
#     TLAT = NCDC_soilcnst(:,5); # TLAT is the negative tangent of the 
#                                # latitude (where the latitude is in 
#                                # radians).
#     # For efficiency, move lines 201-208 above line 59.
#     
#     PHI = [-0.3865982; -0.2316132; -0.0378180; 0.1715539; 0.3458803; ...
#            0.4308320; 0.3916645; 0.2452467; 0.0535511; -0.15583436; ...
#            -0.3340551; -0.4310691];
#     
#     T_loc = T_F(g:d,1); # T_loc is the temperature record (in degrees C) 
#                         # for location j, arranged as a row vector.
#                         
#     T = reshape((T_loc'),12,y)'; # T is the temperature (for location j) 
#                                  # converted from degrees F to degrees C 
#                                  # and reshaped so rows represent years 
#                                  # and columns represent months.
#     # PET_in is the potential evapotranspiration (in inches) for location
#     # j. Pre-allocate for speed.                             
#     PET_in = zeros(size(T));
#     
#     DUM = PHI.*TLAT(j);
#     DK = atan(math.sqrt(1 - DUM.*DUM)./DUM);
#     for m = 1:12
#         if DK[m] < 0
#             DK[m] = 3.141593 + DK[m];
#         DK[m] = (DK[m] + 0.0157)/1.57;
#     for y = 1:y # y is the counter for each year of the data on record for
#                 # each of the different locations.
#         for m = 1:12 # m is the counter for each of the 12 months in a
#                      # year.
#             # Calculate PET for Temperatures <= 32 degrees F.
#             if T(y,m) <= 32
#                 PET_in(y,m) = 0.0;
#             # Calculate PET for Temperatures >= 80 degrees F.
#             elseif T(y,m) >= 80
#                 PET_in(y,m) = (sin(T(y,m)/57.3 - 0.166) - 0.76)*DK[m];
#                 PET_in(y,m) = PET_in(y,m)*days_in_month[m];
#             # Calculate PET for Temperatures <= 32 degrees F and < 80 
#             # degress F.
#             else
#                 DUM = log(T(y,m) - 32);
#                 PET_in(y,m) = (exp(-3.863233 + B(j)*1.715598 - B(j)* ...
#                                log(h(j)) + B(j)*DUM))*DK[m];
#                 PET_in(y,m) = PET_in(y,m)*days_in_month[m];
#     
#     # Catalogue PET for all locations.
#     PET = [PET; PET_in];
#     #}     

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def pdinew_water_balance(T,
                         P,
                         AWC,
                         TLA,
                         B, 
                         H,
                         begin_year=1895):

    '''
    Computes a water balance accounting for monthly time series. Translated from the Fortran code pdinew.f
    
    :param T: monthly average temperature values, starting in January of the initial year 
    :param P: monthly total precipitation values, starting in January of the initial year 
    :param AWC: available water capacity, below (not including) the top inch
    :param B: read from soil constants file 
    :param H: read from soil constants file
    :param begin_year: initial year of the dataset  
    :param TLA: negative tangent of the latitude
    '''
    
    # find the number of years from the input array, assume shape (months)
    
    # reshape the precipitation array from 1-D (assumed to be total months) to (years, 12) with the second  
    # dimension being calendar months, and the final/missing monthly values of the final year padded with NaNs
    T = utils.reshape_to_years_months(T)
    P = utils.reshape_to_years_months(P)
    total_years = P.shape[0]
    
    WCTOP = 1.0
    SS  = WCTOP
    SU = AWC
    WCTOT = AWC + WCTOP

    PHI = np.array([-0.3865982, -0.2316132, -0.0378180, 0.1715539, 0.3458803, 0.4308320, \
                     0.3916645, 0.2452467, 0.0535511, -0.15583436, -0.3340551, -0.4310691])
    
    # initialize the data arrays with NaNs    
    pdat = np.full((total_years, 12), np.NaN)
    spdat = np.full((total_years, 12), np.NaN)
    pedat = np.full((total_years, 12), np.NaN)
    pldat = np.full((total_years, 12), np.NaN)
    prdat = np.full((total_years, 12), np.NaN)
    rdat = np.full((total_years, 12), np.NaN)
    tldat = np.full((total_years, 12), np.NaN)
    etdat = np.full((total_years, 12), np.NaN)
    rodat = np.full((total_years, 12), np.NaN)
    tdat = np.full((total_years, 12), np.NaN)
    sssdat = np.full((total_years, 12), np.NaN)
    ssudat = np.full((total_years, 12), np.NaN)

    #       loop on years and months
    end_year = begin_year + total_years
    years_range = range(begin_year, end_year)
    for year_index, year in enumerate(years_range):
    
        for month_index in range(12):
    
            temperature = T[year_index, month_index]
            precipitation = P[year_index, month_index]
            
            #-----------------------------------------------------------------------
            #     HERE START THE WATER BALANCE CALCULATIONS
            #-----------------------------------------------------------------------
            SP = SS + SU
            PR = AWC + WCTOP - SP

            #-----------------------------------------------------------------------
            #     1 - CALCULATE PE (POTENTIAL EVAPOTRANSPIRATION)   
            #-----------------------------------------------------------------------
            if temperature <= 32.0:
                PE   = 0.0
            else:  
                DUM = PHI[month_index] * TLA 
                DK = math.atan(math.sqrt(1.0 - (DUM * DUM)) / DUM)   
                if DK < 0.0:
                    DK = 3.141593 + DK  
                DK   = (DK + 0.0157) / 1.57  
                if temperature >= 80.0:
                    PE = (math.sin((temperature / 57.3) - 0.166) - 0.76) * DK
                else:  
                    DUM = math.log(temperature - 32.0)
                    PE = math.exp(-3.863233 + (B * 1.715598) - (B * math.log(H)) + (B * DUM)) * DK 
        
            #-----------------------------------------------------------------------
            #     CONVERT DAILY TO MONTHLY  
            #-----------------------------------------------------------------------
            PE = PE * calendar.monthrange(year, month_index + 1)[1]

            #-----------------------------------------------------------------------
            #     2 - PL  POTENTIAL LOSS
            #-----------------------------------------------------------------------
            if SS >= PE:
                PL  = PE  
            else:  
                PL = ((PE - SS) * SU) / (AWC + WCTOP) + SS   
                PL = min(PL, SP)   
        
            #-----------------------------------------------------------------------
            #     3 - CALCULATE RECHARGE, RUNOFF, RESIDUAL MOISTURE, LOSS TO BOTH   
            #         SURFACE AND UNDER LAYERS, DEPENDING ON STARTING MOISTURE  
            #         CONTENT AND VALUES OF PRECIPITATION AND EVAPORATION.  
            #-----------------------------------------------------------------------
            if precipitation >= PE:
                #     ----------------- PRECIP EXCEEDS POTENTIAL EVAPORATION
                ET = PE   
                TL = 0.0  
                if (precipitation - PE) > (WCTOP - SS):
                    #         ------------------------------ EXCESS PRECIP RECHARGES
                    #                                        UNDER LAYER AS WELL AS UPPER   
                    RS = WCTOP - SS  
                    SSS = WCTOP  
                    if (precipitation - PE - RS) < (AWC - SU):
                    #             ---------------------------------- BOTH LAYERS CAN TAKE   
                    #                                                THE ENTIRE EXCESS  
                        RU = precipitation - PE - RS  
                        RO = 0.0  
                    else:  
                        #             ---------------------------------- SOME RUNOFF OCCURS 
                        RU = AWC - SU   
                        RO = precipitation - PE - RS - RU 

                    SSU = SU + RU 
                    R   = RS + RU 
                else:  
                    #         ------------------------------ ONLY TOP LAYER RECHARGED   
                    R  = precipitation - PE  
                    SSS = SS + precipitation - PE 
                    SSU = SU  
                    RO  = 0.0 

            else:
                #     ----------------- EVAPORATION EXCEEDS PRECIPITATION   
                R  = 0.0  
                if SS >= (PE - precipitation):
                #         ----------------------- EVAP FROM SURFACE LAYER ONLY  
                    SL  = PE - precipitation  
                    SSS = SS - SL 
                    UL  = 0.0 
                    SSU = SU  
                else:
                    #         ----------------------- EVAP FROM BOTH LAYERS 
                    SL  = SS  
                    SSS = 0.0 
                    UL  = (PE - precipitation - SL) * SU / (WCTOT)  
                    UL  = min(UL, SU)
                    SSU = SU - UL 

                TL  = SL + UL 
                RO  = 0.0 
                ET  = precipitation  + SL + UL

            # set the climatology and water balance data array values for this year/month time step
            pdat[year_index, month_index] = precipitation
            spdat[year_index, month_index] = SP
            pedat[year_index, month_index] = PE
            pldat[year_index, month_index] = PL
            prdat[year_index, month_index] = PR
            rdat[year_index, month_index] = R
            tldat[year_index, month_index] = TL
            etdat[year_index, month_index] = ET
            rodat[year_index, month_index] = RO
            tdat[year_index, month_index] = temperature
            sssdat[year_index, month_index] = SSS
            ssudat[year_index, month_index] = SSU
      
            # reset the upper and lower soil moisture values
            SS = SSS
            SU = SSU

    return pdat, spdat, pedat, pldat, prdat, rdat, tldat, etdat, rodat, tdat, sssdat, ssudat
    
#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def water_balance(AWC,
                  PET,
                  P):

    # This function calculates the Thornthwaite water balance using inputs from
    # the PET function and user-loaded precipitation data.
    
    # NOTE: PET AND P SHOULD BE READ IN AS A MATRIX IN INCHES. AWC IS A
    # CONSTANT AND SHOULD BE READ IN INCHES AS WELL.
    
    # P and PET should be in inches, flatten to a 1-D array
    PET = PET.flatten() 
    P = P.flatten()
    
    total_months = PET.shape[0]

    ET = np.zeros((total_months,))
    PR = np.zeros((total_months,))
    R = np.zeros((total_months,))
    Rs = np.zeros((total_months,))
    Ru = np.zeros((total_months,))
    RO = np.zeros((total_months,))
    PRO = np.zeros((total_months,))
    S = np.zeros((total_months,))
    Ss = np.zeros((total_months,))
    Su = np.zeros((total_months,))
    L = np.zeros((total_months,))
    Ls = np.zeros((total_months,))
    Lu = np.zeros((total_months,))
    PL = np.zeros((total_months,))
    PLs = np.zeros((total_months,))
    PLu = np.zeros((total_months,))
    
    # A is the difference between the soil moisture in the surface soil layer and the potential evapotranspiration.
    A = np.zeros((total_months,))
        
    # B is the difference between the precipitation and potential evapotranspiration, i.e. the excess precipitation
    B = np.zeros((total_months,))

    # C is the amount of room (in inches) in the surface soil layer that can be recharged with precipitation
    C = np.zeros((total_months,))

    # D is the amount of excess precipitation (in inches) that is left over after the surface soil layer is recharged
    D = np.zeros((total_months,))
    
    # E is the amount of room (in inches) in the underlying soil layer that is available to be recharged with excess precipitation
    E = np.zeros((total_months,))

    ## CONSTANTS
    
    # NOTE: SOIL MOISTURE STORAGE IS HANDLED BY DIVIDING THE SOIL INTO TWO
    # LAYERS AND ASSUMING THAT 1 INCH OF WATER CAN BE STORED IN THE SURFACE
    # LAYER. AWC IS THE COMBINED AVAILABLE MOISTURE CAPACITY IN BOTH SOIL
    # LAYERS. THE UNDERLYING LAYER HAS AN AVAILABLE CAPACITY THAT DEPENDS 
    # ON THE SOIL CHARACTERISTICS OF THE LOCATION. THE SOIL MOISTURE 
    # STORAGE WITHIN THE SURFACE LAYER (UNDERLYING LAYER) IS THE AMOUNT OF 
    # AVAILABLE MOISTURE STORED AT THE BEGINNING OF THE MONTH IN THE 
    # SURFACE (UNDERLYING) LAYER.
    
    # Ss_AWC is the available moisture capacity in the surface soil layer; it is a constant across all locations.
    Ss_AWC = 1 
    
    #!!!!!! VALIDATE !!!!!!!!!!!!!!!!!!!!!!!!!!
    #
    # proposed fix for locations where the AWC is less than 1.0 inch
    #
    if AWC < 1.0:
        Ss_AWC = AWC
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!    
    

    # Su_AWC is the available moisture capacity in the underlying soil layer; it is a location-specific constant.
    Su_AWC = AWC - Ss_AWC
    
    ## INITIAL CONDITIONS
    
    # NOTE: AS THE FIRST STEP IN THE CALCULATION OF THE PALMER DROUGHT 
    # INDICES IS A WATER BALANCE, THE CALCULATION SHOULD BE INITIALIZED 
    # DURING A MONTH AND YEAR IN WHICH THE SOIL MOISTURE STORAGE CAN BE 
    # ASSUMED TO BE FULL.
    
    # S0 = AWC is the initial combined soil moisture storage 
    # in both soil layers. Within the following water balance
    # calculation loop, S0 is the soil moisture storage in
    # both soil layers at the beginning of each month.
    S0 = AWC 
    
    # Ss0 = 1 is the initial soil moisture storage in the surface 
    # soil layer. Within the following water balance calculation
    # loop, Ss0 is the soil moisture storage in the surface soil 
    # layer at the beginning of each month.
    Ss0 = 1 
    
    #!!!!!! VALIDATE !!!!!!!!!!!!!!!!!!!!!!!!!!
    #
    # proposed fix for locations where the AWC is less than 1.0 inch
    #
    if AWC < 1.0:
        Ss0 = AWC
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!    

    # Su0 = Su_AWC is the initial soil moisture storage in 
    # the underlying soil layer. Within the following 
    # water balance calculation loop, Su0 is the soil
    # moisture storage in the underlying soil layer at the 
    # beginning of each month.
    Su0 = Su_AWC
    
    ## CALCULATION OF THE WATER BALANCE
    
    # THE FIRST PART OF PALMER'S METHOD FOR CALCULATING THE PDSI INVOLVES 
    # THE CALCULATION OF  A WATER BALANCE USING HISTORIC RECORDS OF 
    # PRECIPITATION AND TEMPERATURE AND THORNTHWAITE'S METHOD.
    
    # k is the counter for each month of data on record
    for k in range(total_months):

        ## VARIABLE DEFINITIONS
        
        # P is the historical, monthly precipitation for the location.
        
        # Ss is the soil moisture storage in the surface layer at the end of the month.
        
        # Su is the soil moisture storage in the underlying layer at the end of the month.
        
        # S is the combined soil moisture storage in the combined surface 
        # and underlying soil moisture storage layers at the end of the month.
        
        # ET is the actual evapotranspiration from the combined surface and underlying soil moisture storage layers.
        
        # Ls is the actual soil moisture loss from the surface soil moisture storage layer.
        
        # Lu is the actual soil moisture loss from the underlying soil moisture storage layer.
        
        # L is the actual soil moisture loss from the combined surface and underlying soil moisture storage layers.
        
        # PLs is the potential soil moisture loss from the surface soil moisture storage layer.
        
        # PLu is the potential soil moisture loss from the underlying soil moisture storage layer.
        
        # PL is the potential soil moisture loss from the combined surface and underlying soil moisture storage layers.
        
        # Rs is the actual recharge to the surface soil moisture storage layer.
        
        # Ru is the actual recharge to the underlying soil moisture storage layer.
        
        # R is the actual recharge to the combined surface and underlying soil moisture storage layers.
        
        # PR is the potential recharge to the combined surface and underlying 
        # soil moisture storage layers at the beginning of the month.
        PR[k] = AWC - S0
        
        # RO is the actual runoff from the combined surface and underlying soil moisture storage layers.
        
        # PRO is the potential runoff. According to Alley (1984),
        # PRO = AWC - PR = Ss + Su; here Ss and Su refer to those values at
        # the beginning of the month: Ss0 and Su0.
        PRO[k] = AWC - PR[k]
        
        # A is the difference between the soil moisture in the surface soil layer and the potential evapotranspiration.
        A[k] = Ss0 - PET[k]
        
        # B is the difference between the precipitation and potential
        # evapotranspiration - it is the excess precipitation.
        B[k] = P[k] - PET[k]
        
        ## INTERNAL CALCULATIONS
        
        # A >= 0 indicates that there is sufficient moisture in the surface soil layer to satisfy the PET 
        # requirement for month k. Therefore, there is potential moisture loss from only the surface soil layer.
        if A[k] >= 0: 
            PLs[k] = PET[k]         
            PLu[k] = 0
            
        else: 
            # A < 0 indicates that there is not sufficient moisture in the surface soil layer to satisfy the PET requirement for month k.
            # Therefore, there is potential moisture loss from both the surface and underlying soil layers. The equation for PLu is
            # given in Alley (1984).
            PLs[k] = Ss0
            PLu[k] = ((PET[k] - PLs[k]) * Su0) / AWC
            
            # Su0 >= PLu indicates that there is sufficient moisture in the underlying soil layer to (along with the moisture in
            # the surface soil layer) satisfy the PET requirement for month k; therefore, PLu is as calculated according to the equation 
            # given in Alley (1984).
            if Su0 >= PLu[k]: 
                PLu[k] = ((PET[k] - PLs[k]) * Su0) / AWC
            
            else:
                # Su0 < PLu indicates that there is not sufficient moisture in the underlying soil layer to (along with the 
                # moisture in the surface soil layer) satisfy the PET requirement for month k; therefore, PLu is equal to the 
                # moisture storage in the underlying soil layer at the beginning of the month.
                PLu[k] = Su0
        
        PL[k] = PLs[k] + PLu[k]
        
        if B[k] >= 0:
            # B >= 0 indicates that there is sufficient 
            # precipitation during month k to satisfy the PET 
            # requirement for month k - i.e., there is excess 
            # precipitation. Therefore, there is no moisture loss 
            # from either soil layer.
            
            # C is the amount of room (in inches) in the
            # surface soil layer that can be recharged with
            # precipitation. Here 1 refers to the
            # approximate number of inches of moisture 
            # allocated to the surface soil layer.
            C[k] = 1 - Ss0 
            
            if C[k] >= B[k]:
                # C >= B indicates that there is AT LEAST enough room in the surface soil layer for recharge than there is excess
                # precipitation. Therefore, precipitation will recharge ONLY the surface soil layer, and there is NO runoff and 
                # NO soil moisture loss from either soil layer.
                Rs[k] = B[k]
                Ls[k] = 0
                Ss[k] = Ss0 + Rs[k]
                Ru[k] = 0
                Lu[k] = 0
                Su[k] = Su0
                RO[k] = 0

            else:
                # C < B indicates that there is more excess precipitation 
                # than there is room in the surface soil layer for 
                # recharge. Therefore, the excess precipitation will 
                # recharge BOTH the surface soil layer and the underlying 
                # soil layer, and there is NO soil moisture loss from 
                # either soil layer.
                Rs[k] = C[k]
                Ls[k] = 0 
                Ss[k] = 1   # the approximate number of inches of moisture allocated to the surface soil layer
                D[k] = B[k] - Rs[k] # amount of excess precipitation (in inches) left over after the surface soil layer is recharged
                E[k] = Su_AWC - Su0  # amount of room (in inches) in the underlying soil layer available to be recharged with excess precipitation
                if E[k] > D[k]: 
                    # E > D indicates that there is more room in the underlying soil layer than there is excess precipitation available  
                    # after recharge to the surface soil layer. Therefore, there is no runoff.
                    Ru[k] = D[k]
                    RO[k] = 0
            
                else: 
                    # E <= D indicates that there is AT MOST enough room 
                    # in the underlying soil layer for the excess
                    # precipitation available after recharge to the 
                    # surface soil layer. In the case that there is enough 
                    # room, there is no runoff. In the case that there is 
                    # not enough room, runoff occurs.
                    Ru[k] = E[k]
                    RO[k] = D[k] - Ru[k]

                # Since there is more excess precipitation than there is room in the surface soil layer for recharge,
                # the soil moisture storage in the underlying soil layer at the end of the month is equal to the storage at 
                # the beginning of the month plus any recharge to the underlying soil layer.
                Lu[k] = 0
                Su[k] = Su0 + Ru[k] 

            # Since there is sufficient precipitation during month k to satisfy the PET
            # requirement for month k, the actual evapotranspiration is equal to PET.
            ET[k] = PET[k] 
            
        else: 
            # B < 0 indicates that there is not sufficient precipitation
            # during month k to satisfy the PET requirement for month k -
            # i.e., there is NO excess precipitation. Therefore, soil 
            # moisture loss occurs, and there is NO runoff and NO recharge 
            # to either soil layer.
            if Ss0 >= abs(B[k]):
                # Ss0 >= abs(B) indicates that there is AT LEAST sufficient moisture in the surface soil layer at the beginning 
                # of the month k to satisfy the PET requirement for month k. Therefore, soil moisture loss occurs from ONLY the surface
                # soil layer, and the soil moisture storage in the surface soil layer at the end of the month is equal to the storage
                # at the beginning of the month less any loss from the surface soil layer.
                Ls[k] = abs(B[k])
                Rs[k] = 0
                Ss[k] = Ss0 - Ls[k]
                Lu[k] = 0
                Ru[k] = 0
                Su[k] = Su0
            else: 
                # Ss0 < abs(B) indicates that there is NOT sufficient moisture in the surface soil layer at the beginning of 
                # month k to satisfy the PET requirement for month k. Therefore, soil moisture loss occurs from BOTH the 
                # surface and underlying soil layers, and Lu is calculated according to the equation given in Alley (1984).
                # The soil moisture storage in the underlying soil layer at the end of the month is equal to the storage 
                # at the beginning of the month less the loss from the underlying soil layer.
                Ls[k] = Ss0
                Rs[k] = 0
                Ss[k] = 0
                Lu[k] = min((abs(B[k]) - Ls[k]) * Su0 / (AWC), Su0)
                #*
                #
                # Lu[k] = min((abs(B[k]) - Ls[k])*Su0/(AWC + 1),Su0);
                # NOTE: This equation was used by the NCDC in their FORTRAN code
                # prior to 2013. See Jacobi et al. (2013) for a full explanation. 
                #
                #*
                Ru[k] = 0
                Su[k] = Su0 - Lu[k]

            # Since there is NOT sufficient precipitation during month k to satisfy the PET requirement for month k, the actual 
            # evapotranspiration is equal to precipitation plus any soil moisture loss from BOTH the surface and underlying soil layers.
            RO[k] = 0
            ET[k] = P[k] + Ls[k] + Lu[k] 
            
        R[k] = Rs[k] + Ru[k]
        L[k] = Ls[k] + Lu[k]
        S[k] = Ss[k] + Su[k]
        
        # DEBUG ONLY -- REMOVE
        if R[k] < 0:
            logger.warn('Trouble, negative recharge for month {0}'.format(k))
        if L[k] < 0:
            logger.warn('Trouble, negative loss for month {0}'.format(k))
        
        # S0, Ss0, and Su0 are reset to their end of the current month [k]
        # values - S, Ss, and Su0, respectively - such that they can be
        # used as the beginning of the month values for the next month 
        # (k + 1).
        S0 = S[k]
        Ss0 = Ss[k]
        Su0 = Su[k]
        
    return ET, PR, R, RO, PRO, L, PL 
          
#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def _cafec_coefficients(P,
                        PET,
                        ET,
                        PR,
                        R,
                        RO,
                        PRO,
                        L,
                        PL,
                        data_start_year,
                        calibration_start_year,
                        calibration_end_year):
    '''
    This function calculates CAFEC coefficients used for computing Palmer's Z index using inputs from 
    the water balance function.
    
    :param P: 1-D numpy.ndarray of monthly precipitation observations, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PET: 1-D numpy.ndarray of monthly potential evapotranspiration values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param ET: 1-D numpy.ndarray of monthly evapotranspiration values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PR: 1-D numpy.ndarray of monthly potential recharge values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param R: 1-D numpy.ndarray of monthly recharge values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param RO: 1-D numpy.ndarray of monthly runoff values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PRO: 1-D numpy.ndarray of monthly potential runoff values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param L: 1-D numpy.ndarray of monthly loss values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PL: 1-D numpy.ndarray of monthly potential loss values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param data_start_year: initial year of the input arrays, i.e. the first element of each of the input arrays 
                            is assumed to correspond to January of this initial year
    :param calibration_start_year: initial year of the calibration period, should be greater than or equal to the data_start_year
    :param calibration_end_year: final year of the calibration period
    :return 1-D numpy.ndarray of Z-Index values, with shape corresponding to the input arrays
    :rtype: numpy.ndarray of floats
    '''
    
    # the potential (PET, ET, PR, PL) and actual (R, RO, S, L, P) water balance arrays are reshaped as 2-D arrays  
    # (matrices) such that the rows of each matrix represent years and the columns represent calendar months
    PET = utils.reshape_to_years_months(PET)
    ET = utils.reshape_to_years_months(ET)
    PR = utils.reshape_to_years_months(PR)
    PL = utils.reshape_to_years_months(PL)
    R = utils.reshape_to_years_months(R)
    RO = utils.reshape_to_years_months(RO)
    PRO = utils.reshape_to_years_months(PRO)
    L = utils.reshape_to_years_months(L)
    P = utils.reshape_to_years_months(P)
        
    # ALPHA, BETA, GAMMA, DELTA CALCULATIONS
    # A calibration period is used to calculate alpha, beta, gamma, and 
    # and delta, four coefficients dependent on the climate of the area being
    # examined. The NCDC and CPC use the calibration period January 1931
    # through December 1990 (cf. Karl, 1986; Journal of Climate and Applied 
    # Meteorology, Vol. 25, No. 1, January 1986).
    
    #!!!!!!!!!!!!!
    # TODO make sure calibration years range is valid, i.e. within actual data years range 
    
    # determine the array (year axis) indices for the calibration period
    total_data_years = int(P.shape[0] / 12)
    data_end_year = data_start_year + total_data_years - 1
    total_calibration_years = calibration_end_year - calibration_start_year + 1
    calibration_start_year_index = calibration_start_year - data_start_year
    calibration_end_year_index = calibration_end_year - data_start_year 
    
    # get calibration period arrays
    if (calibration_start_year > data_start_year) or (calibration_end_year < data_end_year):
        P_calibration = P[calibration_start_year_index:calibration_end_year_index + 1]
        ET_calibration = ET[calibration_start_year_index:calibration_end_year_index + 1]
        PET_calibration = PET[calibration_start_year_index:calibration_end_year_index + 1]
        R_calibration = R[calibration_start_year_index:calibration_end_year_index + 1]
        PR_calibration = PR[calibration_start_year_index:calibration_end_year_index + 1]
        L_calibration = L[calibration_start_year_index:calibration_end_year_index + 1]
        PL_calibration = PL[calibration_start_year_index:calibration_end_year_index + 1]
        RO_calibration = RO[calibration_start_year_index:calibration_end_year_index + 1]
        PRO_calibration = PRO[calibration_start_year_index:calibration_end_year_index + 1]
    else:
        P_calibration = P
        ET_calibration = ET
        PET_calibration = PET
        R_calibration = R
        PR_calibration = PR
        L_calibration = L
        PL_calibration = PL
        RO_calibration = RO
        PRO_calibration = PRO

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        
        # get averages for each calendar month (compute means over the year axis, giving an average for each calendar month over all years)
        P_bar = np.nanmean(P_calibration, axis=0)
        ET_bar = np.nanmean(ET_calibration, axis=0)
        PET_bar = np.nanmean(PET_calibration, axis=0)
        R_bar = np.nanmean(R_calibration, axis=0)
        PR_bar = np.nanmean(PR_calibration, axis=0)
        L_bar = np.nanmean(L_calibration, axis=0)
        PL_bar = np.nanmean(PL_calibration, axis=0)
        RO_bar = np.nanmean(RO_calibration, axis=0)
        PRO_bar = np.nanmean(PRO_calibration, axis=0)
            
        # (calendar) monthly CAFEC coefficients
        alpha = np.empty((12,))
        beta = np.empty((12,))
        gamma = np.empty((12,))
        delta = np.empty((12,))
    
        # compute the alpha, beta, gamma, and delta coefficients for each calendar month
        for i in range(12):
            
            # calculate alpha
            if PET_bar[i] == 0:
                if ET_bar[i] == 0:
                    alpha[i] = 1
                else:
                    alpha[i] = 0
                    #logger.warn('CHECK DATA: PET is less than ET.')
            else:
                alpha[i] = ET_bar[i] / PET_bar[i]
    
            # calculate beta
            if PR_bar[i] == 0:
                if R_bar[i] == 0:
                    beta[i] = 1
                else:
                    beta[i] = 0
                    #logger.warn('CHECK DATA: PR is less than R.')
            else:
                beta[i] = R_bar[i] / PR_bar[i]
    
            # calculate gamma
            if PRO_bar[i] == 0:
                if RO_bar[i] == 0:
                    gamma[i] = 1
                else:
                    gamma[i] = 0
                    #logger.warn('CHECK DATA: PRO is less than RO.')
            else:
                gamma[i] = RO_bar[i] / PRO_bar[i]
    
            # calculate delta
            if PL_bar[i] == 0:
                if L_bar[i] == 0:
                    delta[i] = 1
                else:
                    delta[i] = 0
                    #logger.warn('CHECK DATA: PL is less than L.')
            else:
                delta[i] = L_bar[i] / PL_bar[i]

    return alpha, beta, delta, gamma

#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def pdinew_cafec_coefficients(P,
                              PET,
                              ET,
                              PR,
                              R,
                              RO,
                              PRO,
                              L,
                              PL,
                              SP,
                              data_start_year,
                              calibration_start_year,
                              calibration_end_year):
    '''
    This function calculates CAFEC coefficients used for computing Palmer's Z index using inputs from 
    the water balance function. Translated from Fortran pdinew.f
    
    :param P: 1-D numpy.ndarray of monthly precipitation observations, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PET: 1-D numpy.ndarray of monthly potential evapotranspiration values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param ET: 1-D numpy.ndarray of monthly evapotranspiration values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PR: 1-D numpy.ndarray of monthly potential recharge values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param R: 1-D numpy.ndarray of monthly recharge values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param RO: 1-D numpy.ndarray of monthly runoff values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PRO: 1-D numpy.ndarray of monthly potential runoff values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param L: 1-D numpy.ndarray of monthly loss values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PL: 1-D numpy.ndarray of monthly potential loss values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param SP: 1-D numpy.ndarray of monthly SP values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param data_start_year: initial year of the input arrays, i.e. the first element of each of the input arrays 
                            is assumed to correspond to January of this initial year
    :param calibration_start_year: initial year of the calibration period, should be greater than or equal to the data_start_year
    :param calibration_end_year: final year of the calibration period
    :return 1-D numpy.ndarray of Z-Index values, with shape corresponding to the input arrays
    :rtype: numpy.ndarray of floats
    '''
    
    # the potential (PET, ET, PR, PL) and actual (R, RO, S, L, P) water balance arrays are reshaped as 2-D arrays  
    # (matrices) such that the rows of each matrix represent years and the columns represent calendar months
    PET = utils.reshape_to_years_months(PET)
    ET = utils.reshape_to_years_months(ET)
    PR = utils.reshape_to_years_months(PR)
    PL = utils.reshape_to_years_months(PL)
    R = utils.reshape_to_years_months(R)
    RO = utils.reshape_to_years_months(RO)
    PRO = utils.reshape_to_years_months(PRO)
    L = utils.reshape_to_years_months(L)
    P = utils.reshape_to_years_months(P)
    SP = utils.reshape_to_years_months(SP)
        
    # ALPHA, BETA, GAMMA, DELTA CALCULATIONS
    # A calibration period is used to calculate alpha, beta, gamma, and 
    # and delta, four coefficients dependent on the climate of the area being
    # examined. The NCDC and CPC use the calibration period January 1931
    # through December 1990 (cf. Karl, 1986; Journal of Climate and Applied 
    # Meteorology, Vol. 25, No. 1, January 1986).
    
    #!!!!!!!!!!!!!
    # TODO make sure calibration years range is valid, i.e. within actual data years range 
    
    # determine the array (year axis) indices for the calibration period
    total_data_years = int(P.shape[0] / 12)
    data_end_year = data_start_year + total_data_years - 1
    total_calibration_years = calibration_end_year - calibration_start_year + 1
    calibration_start_year_index = calibration_start_year - data_start_year
    calibration_end_year_index = calibration_end_year - data_start_year 
    
    # get calibration period arrays
    if (calibration_start_year > data_start_year) or (calibration_end_year < data_end_year):
        P_calibration = P[calibration_start_year_index:calibration_end_year_index + 1]
        ET_calibration = ET[calibration_start_year_index:calibration_end_year_index + 1]
        PET_calibration = PET[calibration_start_year_index:calibration_end_year_index + 1]
        R_calibration = R[calibration_start_year_index:calibration_end_year_index + 1]
        PR_calibration = PR[calibration_start_year_index:calibration_end_year_index + 1]
        L_calibration = L[calibration_start_year_index:calibration_end_year_index + 1]
        PL_calibration = PL[calibration_start_year_index:calibration_end_year_index + 1]
        RO_calibration = RO[calibration_start_year_index:calibration_end_year_index + 1]
        PRO_calibration = PRO[calibration_start_year_index:calibration_end_year_index + 1]
        SP_calibration = SP[calibration_start_year_index:calibration_end_year_index + 1]
    else:
        P_calibration = P
        ET_calibration = ET
        PET_calibration = PET
        R_calibration = R
        PR_calibration = PR
        L_calibration = L
        PL_calibration = PL
        RO_calibration = RO
        PRO_calibration = PRO
        SP_calibration = SP

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        
#         # get averages for each calendar month (compute means over the year axis, giving an average for each calendar month over all years)
#         P_bar = np.nanmean(P_calibration, axis=0)
#         ET_bar = np.nanmean(ET_calibration, axis=0)
#         PET_bar = np.nanmean(PET_calibration, axis=0)
#         R_bar = np.nanmean(R_calibration, axis=0)
#         PR_bar = np.nanmean(PR_calibration, axis=0)
#         L_bar = np.nanmean(L_calibration, axis=0)
#         PL_bar = np.nanmean(PL_calibration, axis=0)
#         RO_bar = np.nanmean(RO_calibration, axis=0)
#         PRO_bar = np.nanmean(PRO_calibration, axis=0)
            
        # get sums for each calendar month (compute sums over the year axis, giving a sum for each calendar month over all years)
        P_sum = np.nansum(P_calibration, axis=0)
        ET_sum = np.nansum(ET_calibration, axis=0)
        PET_sum = np.nansum(PET_calibration, axis=0)
        R_sum = np.nansum(R_calibration, axis=0)
        PR_sum = np.nansum(PR_calibration, axis=0)
        L_sum = np.nansum(L_calibration, axis=0)
        PL_sum = np.nansum(PL_calibration, axis=0)
        RO_sum = np.nansum(RO_calibration, axis=0)
        SP_sum = np.nansum(SP_calibration, axis=0)
            
        # (calendar) monthly CAFEC coefficients
        alpha = np.empty((12,))
        beta = np.empty((12,))
        gamma = np.empty((12,))
        delta = np.empty((12,))
        t_ratio = np.empty((12,))
    
        # compute the alpha, beta, gamma, and delta coefficients for each calendar month
        for i in range(12):
            
            #     ALPHA CALCULATION 
            #     ----------------- 
            if PET_sum[i] != 0.0:   
                alpha[i] = ET_sum[i] / PET_sum[i]  
            else:  
                if ET_sum[i] == 0.0:  
                    alpha[i] = 1.0  
                else:  
                    alpha[i] = 0.0  
            
            #   
            #     BETA CALCULATION  
            #     ----------------  
            if PR_sum[i] != 0.0:  
                beta[i] = R_sum[i] / PR_sum[i] 
            else:  
                if R_sum[i] == 0.0:   
                    beta[i] = 1.0  
                else:  
                    beta[i] = 0.0  

            #   
            #     GAMMA CALCULATION 
            #     ----------------- 
            if SP_sum[i] != 0.0:  
                gamma[i] = RO_sum[i] / SP_sum[i]  
            else:  
                if RO_sum[i] == 0.0:  
                    gamma[i] = 1.   
                else:  
                    gamma[i] = 0.0  

            #   
            #     DELTA CALCULATION 
            #     ----------------- 
            if PL_sum[i] != 0.0:  
                delta[i] = L_sum[i] / PL_sum[i]  
            else:
                delta[i] = 0.0  

            #'T' ratio of average moisture demand to the average moisture supply in the month
            t_ratio[i] = (PET_sum[i] + R_sum[i] + RO_sum[i]) / (P_sum[i] + L_sum[i])

    return alpha, beta, delta, gamma, t_ratio

#-----------------------------------------------------------------------------------------------------------------------
def pdinew_compute_K(alpha,
                     beta,
                     gamma,
                     delta,
                     Pdat,
                     PEdat,
                     PRdat,
                     SPdat,
                     PLdat,
                     t_ratio,
                     begin_year,
                     calibration_begin_year,
                     calibration_end_year):
    
    SABSD = np.zeros((12,))
    
    number_calibration_years = calibration_end_year - calibration_begin_year + 1
    
    # loop over the calibration years
    for j in range(calibration_begin_year - begin_year, calibration_end_year - begin_year + 1):
        for m in range(12):
            
            #-----------------------------------------------------------------------
            #     REREAD MONTHLY PARAMETERS FOR CALCULATION OF 
            #     THE 'K' MONTHLY WEIGHTING FACTORS USED IN Z-INDEX CALCULATION 
            #-----------------------------------------------------------------------
            PHAT = (alpha[m] * PEdat[j, m]) + (beta[m] * PRdat[j, m]) + (gamma[m] * SPdat[j, m]) - (delta[m] * PLdat[j, m])  
            D = Pdat[j, m] - PHAT   
            SABSD[m] = SABSD[m] + abs(D) 

    SWTD = 0.0
    AKHAT = np.empty((12,))
    for m in range(12):
        DBAR = SABSD[m] / number_calibration_years 
        AKHAT[m] = 1.5 * math.log10((t_ratio[m] + 2.8) / DBAR) + 0.5
        SWTD = SWTD + (DBAR * AKHAT[m])  

    AK = np.empty((12,))
    for m in range(12):
        AK[m] = 17.67 * AKHAT[m] / SWTD 
 
    return AK

#-----------------------------------------------------------------------------------------------------------------------
def pdinew_zindex_pdsi(P,
                       PE,
                       PR,
                       SP,
                       PL,
                       PPR,
                       alpha,
                       beta,
                       gamma,
                       delta,
                       AK):

    P = utils.reshape_to_years_months(P)
    PPR = utils.reshape_to_years_months(PPR)
#     eff = np.full(P.shape, np.NaN)
    CP = np.full(P.shape, np.NaN)
    Z = np.full(P.shape, np.NaN)
    
    PDSI = np.full(P.shape, np.NaN)
    PHDI = np.full(P.shape, np.NaN)
    WPLM = np.full(P.shape, np.NaN)
    
    nbegyr = 1895
    nendyr = 2017

    PV = 0.0
    V   = 0.0 
    PRO = 0.0 
    X1  = 0.0 
    X2  = 0.0 
    X3  = 0.0 
    K8  = 0
    k8max = 0

    indexj = np.empty(P.shape)
    indexm = np.empty(P.shape)
    PX1 = np.zeros(P.shape)
    PX2 = np.zeros(P.shape)
    PX3 = np.zeros(P.shape)
    SX1 = np.zeros(P.shape)
    SX2 = np.zeros(P.shape)
    SX3 = np.zeros(P.shape)
    SX = np.full(P.shape, np.NaN)
    X = np.full(P.shape, np.NaN)
    
    for j in range(P.shape[0]):    
               
        for m in range(12):

            indexj[K8] = j
            indexm[K8] = m

            #-----------------------------------------------------------------------
            #     LOOP FROM 160 TO 230 REREADS data FOR CALCULATION OF   
            #     THE Z-INDEX (MOISTURE ANOMALY) AND PDSI (VARIABLE X). 
            #     THE FINAL OUTPUTS ARE THE VARIABLES PX3, X, AND Z  WRITTEN
            #     TO FILE 11.   
            #-----------------------------------------------------------------------
            ZE = 0.0 
            UD = 0.0 
            UW = 0.0 
            CET = alpha[m] * PE[j, m]
            CR = beta[m] * PR[j, m]
            CRO = gamma[m] * SP[j, m]
            CL = delta[m] * PL[j, m]
            CP[j, m]  = CET + CR + CRO - CL 
            CD = P[j, m] - CP[j, m]  
            Z[j, m] = AK[m] * CD 
            if PRO == 100.0 or PRO == 0.0:  
            #     ------------------------------------ NO ABATEMENT UNDERWAY
            #                                          WET OR DROUGHT WILL END IF   
            #                                             -0.5 =< X3 =< 0.5   
                if abs(X3) <= 0.5:
                #         ---------------------------------- END OF DROUGHT OR WET  
                    PV = 0.0 
                    PPR[j, m] = 0.0 
                    PX3[j, m] = 0.0 
                    #             ------------ BUT CHECK FOR NEW WET OR DROUGHT START FIRST
                    # GOTO 200 in pdinew.f
                    # compare to 
                    # PX1, PX2, PX3, X, BT = Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT)
                    # in pdsi_from_zindex()
                    X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_200(PX1,
                                                                          PX2,
                                                                          PX3,
                                                                          X,
                                                                          X1,
                                                                          X2,
                                                                          Z,
                                                                          j,
                                                                          m,
                                                                          K8,
                                                                          PPR,
                                                                          PDSI, 
                                                                          PHDI, 
                                                                          WPLM, 
                                                                          nendyr, 
                                                                          nbegyr, 
                                                                          SX1, 
                                                                          SX2, 
                                                                          SX3, 
                                                                          SX, 
                                                                          indexj, 
                                                                          indexm,
                                                                          PV)
                     
                elif (X3 > 0.5):   
                    #         ----------------------- WE ARE IN A WET SPELL 
                    if (Z[j, m] >= 0.15):   
                        #              ------------------ THE WET SPELL INTENSIFIES 
                        #GO TO 210 in pdinew.f
                        # compare to 
                        # PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_210(K8, 
                                                                              PPR, 
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X1,
                                                                              X2, 
                                                                              X3, 
                                                                              X, 
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm,
                                                                              Z)
                        
                    else:
                        #             ------------------ THE WET STARTS TO ABATE (AND MAY END)  
                        #GO TO 170 in pdinew.f
                        # compare to
                        # Ud, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Ud(k, Ud, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_170(Z, 
                                                                              V, 
                                                                              K8, 
                                                                              PPR,
                                                                              PRO, 
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X, 
                                                                              X1,
                                                                              X2,
                                                                              X3,
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm)                        

                elif (X3 < -0.5):  
                    #         ------------------------- WE ARE IN A DROUGHT 
                    if (Z[j, m] <= -0.15):  
                        #              -------------------- THE DROUGHT INTENSIFIES 
                        #GO TO 210
                        # compare to 
                        # PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_210(K8, 
                                                                              PPR, 
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X1,
                                                                              X2, 
                                                                              X3, 
                                                                              X, 
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm,
                                                                              Z) 
                    else:
                        #             ------------------ THE DROUGHT STARTS TO ABATE (AND MAY END)  
                        #GO TO 180
                        # compare to 
                        # Uw, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Uw(k, Uw, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_180(K8, 
                                                                              PPR, 
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X, 
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm,
                                                                              Z,
                                                                              PV,
                                                                              V)
                         
                else:
                    #     ------------------------------------------ABATEMENT IS UNDERWAY   
                    if X3 > 0.0:
                        
                        #         ----------------------- WE ARE IN A WET SPELL 
                        #GO TO 170 in pdinew.f
                        # compare to
                        # Ud, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Ud(k, Ud, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_170(Z, 
                                                                              V, 
                                                                              K8, 
                                                                              PPR,
                                                                              PRO,
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X, 
                                                                              X1,
                                                                              X2,
                                                                              X3, 
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm)   
                    
                    if X3 <= 0.0:
                        
                        #         ----------------------- WE ARE IN A DROUGHT   
                        #GO TO 180
                        # compare to
                        # Uw, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Uw(k, Uw, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                        # in pdsi_from_zindex()
                        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_180(K8, 
                                                                              PPR, 
                                                                              PX1,
                                                                              PX2, 
                                                                              PX3, 
                                                                              X, 
                                                                              PDSI, 
                                                                              PHDI, 
                                                                              WPLM, 
                                                                              j, 
                                                                              m, 
                                                                              nendyr, 
                                                                              nbegyr, 
                                                                              SX1, 
                                                                              SX2, 
                                                                              SX3, 
                                                                              SX, 
                                                                              indexj, 
                                                                              indexm,
                                                                              Z,
                                                                              PV,
                                                                              V)

    return PDSI, PHDI, WPLM, Z

#-----------------------------------------------------------------------------------------------------------------------
# compare to Function_Ud()
def pdinew_170(Z, 
               V, 
               K8, 
               PPR,
               PRO,
               PX1,
               PX2, 
               PX3, 
               X,
               X1,
               X2,
               X3, 
               PDSI, 
               PHDI, 
               WPLM, 
               j, 
               m, 
               nendyr, 
               nbegyr, 
               SX1, 
               SX2, 
               SX3, 
               SX, 
               indexj, 
               indexm):
    #-----------------------------------------------------------------------
    #      WET SPELL ABATEMENT IS POSSIBLE  
    #-----------------------------------------------------------------------
    UD = Z[j, m] - 0.15  
    PV = UD + min(V, 0.0) 
    if PV >= 0:
        #PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)
        X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_210(K8, 
                                                              PPR, 
                                                              PX1,
                                                              PX2, 
                                                              PX3, 
                                                              X1,
                                                              X2, 
                                                              X3, 
                                                              X, 
                                                              PDSI, 
                                                              PHDI, 
                                                              WPLM, 
                                                              j, 
                                                              m, 
                                                              nendyr, 
                                                              nbegyr, 
                                                              SX1, 
                                                              SX2, 
                                                              SX3, 
                                                              SX, 
                                                              indexj, 
                                                              indexm,
                                                              Z)
    else:
        #     ---------------------- DURING A WET SPELL, PV => 0 IMPLIES
        #                            PROB(END) HAS RETURNED TO 0
        ZE = -2.691 * X3 + 1.5
    
        #-----------------------------------------------------------------------
        #     PROB(END) = 100 * (V/Q)  WHERE:   
        #                 V = SUM OF MOISTURE EXCESS OR DEFICIT (UD OR UW)  
        #                 DURING CURRENT ABATEMENT PERIOD   
        #             Q = TOTAL MOISTURE ANOMALY REQUIRED TO END THE
        #                 CURRENT DROUGHT OR WET SPELL  
        #-----------------------------------------------------------------------
        if PRO == 100.0: 
            #     --------------------- DROUGHT OR WET CONTINUES, CALCULATE 
            #                           PROB(END) - VARIABLE ZE 
            Q = ZE
        else:  
            Q = ZE + V
    
        PPR[j, m] = (PV / Q) * 100.0 
        if PPR[j, m] >= 100.0:
             
              PPR[j, m] = 100.0
              PX3[j, m] = 0.0  
        else:
              
              PX3[j, m] = 0.897 * X3 + Z[j, m] / 3.0

    return X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8

#-----------------------------------------------------------------------------------------------------------------------
def pdinew_180(K8, 
               PPR, 
               PX1,
               PX2, 
               PX3, 
               X, 
               PDSI, 
               PHDI, 
               WPLM, 
               j, 
               m, 
               nendyr, 
               nbegyr, 
               SX1, 
               SX2, 
               SX3, 
               SX, 
               indexj, 
               indexm,
               Z,
               PV,
               V):

        #-----------------------------------------------------------------------
        #      DROUGHT ABATEMENT IS POSSIBLE
        #-----------------------------------------------------------------------
        UW = Z[j, m] + 0.15  
        PV = UW + max(V, 0.0) 
        if (PV <= 0):
            # GOTO 210 in pdinew.f
            # compare to 
            # PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)
            # in pdsi_from_zindex()
            X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8 = pdinew_210(K8, 
                                                                  PPR, 
                                                                  PX1,
                                                                  PX2, 
                                                                  PX3, 
                                                                  X1,
                                                                  X2, 
                                                                  X3, 
                                                                  X, 
                                                                  PDSI, 
                                                                  PHDI, 
                                                                  WPLM, 
                                                                  j, 
                                                                  m, 
                                                                  nendyr, 
                                                                  nbegyr, 
                                                                  SX1, 
                                                                  SX2, 
                                                                  SX3, 
                                                                  SX, 
                                                                  indexj, 
                                                                  indexm,
                                                                  Z)
                
        else:
            #     ---------------------- DURING A DROUGHT, PV =< 0 IMPLIES  
            #                            PROB(END) HAS RETURNED TO 0
            ZE = -2.691 * X3 - 1.5
            #-----------------------------------------------------------------------
            #     PROB(END) = 100 * (V/Q)  WHERE:   
            #                 V = SUM OF MOISTURE EXCESS OR DEFICIT (UD OR UW)  
            #                 DURING CURRENT ABATEMENT PERIOD   
            #             Q = TOTAL MOISTURE ANOMALY REQUIRED TO END THE
            #                 CURRENT DROUGHT OR WET SPELL  
            #-----------------------------------------------------------------------
            if PRO == 100.0: 
                #     --------------------- DROUGHT OR WET CONTINUES, CALCULATE 
                #                           PROB(END) - VARIABLE ZE 
                Q = ZE
                
            else:  
                
                Q = ZE + V

            PPR[j, m] = (PV / Q) * 100.0 
            if PPR[j, m] >= 100.0: 
                PPR[j, m] = 100.0
                PX3[j, m] = 0.0  
            else:
                PX3[j, m] = 0.897 * X3 + Z[j, m] / 3.0
              
        return X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8
        
#-----------------------------------------------------------------------------------------------------------------------
# compare to 
# PX1, PX2, PX3, X, BT = Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT)
# in pdsi_from_zindex()
def pdinew_200(PX1,
               PX2,
               PX3,
               X,
               X1,
               X2,
               Z,
               j,
               m,
               K8,
               PPR,
               PDSI, 
               PHDI, 
               WPLM, 
               nendyr, 
               nbegyr, 
               SX1, 
               SX2, 
               SX3, 
               SX, 
               indexj, 
               indexm,
               PV):
    
    # whether or not an appropriate value for X has been found
    found = False
    
    #-----------------------------------------------------------------------
    #     CONTINUE X1 AND X2 CALCULATIONS.  
    #     IF EITHER INDICATES THE START OF A NEW WET OR DROUGHT,
    #     AND IF THE LAST WET OR DROUGHT HAS ENDED, USE X1 OR X2
    #     AS THE NEW X3.
    #-----------------------------------------------------------------------
    PX1[j, m] = 0.897 * X1 + Z[j, m] / 3.0
    PX1[j, m] = max(PX1[j, m], 0.0)   
    if (PX1[j, m] >= 1.0):   
        
        if (PX3[j, m] == 0.0):   
            #         ------------------- IF NO EXISTING WET SPELL OR DROUGHT   
            #                             X1 BECOMES THE NEW X3 
            X[j, m]   = PX1[j, m] 
            PX3[j, m] = PX1[j, m] 
            PX1[j, m] = 0.0
            iass = 1
            assign(iass, K8, PPR, PX1, PX2, PX3, X, PDSI, PHDI, WPLM, j, m, nendyr, nbegyr, SX1, SX2, SX3, SX, indexj, indexm)
            
            V = PV 
#             eff[j, m] = PV 
            PRO = PPR[j, m] 
            X1  = PX1[j, m] 
            X2  = PX2[j, m] 
            X3  = PX3[j, m] 

            found = True
            
    else:
        PX2[j, m] = 0.897 * X2 + Z[j, m] / 3.0
        PX2[j, m] = min(PX2[j, m], 0.0)   
        if PX2[j, m] <= -1.0:  
            
            if (PX3[j, m] == 0.0):   
                #         ------------------- IF NO EXISTING WET SPELL OR DROUGHT   
                #                             X2 BECOMES THE NEW X3 
                X[j, m]   = PX2[j, m] 
                PX3[j, m] = PX2[j, m] 
                PX2[j, m] = 0.0  
                iass = 2            
                assign(iass, K8, PPR, PX1, PX2, PX3, X, PDSI, PHDI, WPLM, j, m, nendyr, nbegyr, SX1, SX2, SX3, SX, indexj, indexm)
    
                found = True
                
        elif PX3[j, m] == 0.0:   
            #    -------------------- NO ESTABLISHED DROUGHT (WET SPELL), BUT X3=0  
            #                         SO EITHER (NONZERO) X1 OR X2 MUST BE USED AS X3   
            if PX1[j, m] == 0.0:   
            
                X[j, m] = PX2[j, m]   
                iass = 2            
                assign(iass, K8, PPR, PX1, PX2, PX3, X, PDSI, PHDI, WPLM, j, m, nendyr, nbegyr, SX1, SX2, SX3, SX, indexj, indexm)

                found = True

            elif PX2[j, m] == 0:
                
                X[j, m] = PX1[j, m]   
                iass = 1   
                assign(iass, K8, PPR, PX1, PX2, PX3, X, PDSI, PHDI, WPLM, j, m, nendyr, nbegyr, SX1, SX2, SX3, SX, indexj, indexm)
    
                found = True

        #-----------------------------------------------------------------------
        #     AT THIS POINT THERE IS NO DETERMINED VALUE TO ASSIGN TO X,
        #     ALL VALUES OF X1, X2, AND X3 ARE SAVED IN FILE 8. AT A LATER  
        #     TIME X3 WILL REACH A VALUE WHERE IT IS THE VALUE OF X (PDSI). 
        #     AT THAT TIME, THE ASSIGN SUBROUTINE BACKTRACKS THROUGH FILE   
        #     8 CHOOSING THE APPROPRIATE X1 OR X2 TO BE THAT MONTHS X. 
        #-----------------------------------------------------------------------
        elif not found and (K8 > 40):  # STOP 'X STORE ARRAYS FULL'  
            
            SX1[K8] = PX1[j, m] 
            SX2[K8] = PX2[j, m] 
            SX3[K8] = PX3[j, m] 
            X[j, m]  = PX3[j, m] 
            K8 = K8 + 1
            k8max = K8  

    #-----------------------------------------------------------------------
    #     SAVE THIS MONTHS CALCULATED VARIABLES (V,PRO,X1,X2,X3) FOR   
    #     USE WITH NEXT MONTHS DATA 
    #-----------------------------------------------------------------------
    V = PV 
#     eff[j, m] = PV 
    PRO = PPR[j, m] 
    X1  = PX1[j, m] 
    X2  = PX2[j, m] 
    X3  = PX3[j, m] 

    return X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8
 
#-----------------------------------------------------------------------------------------------------------------------
# compare to Between0s()
# 
# typical usage:
#
# PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)
def pdinew_210(K8, 
               PPR, 
               PX1,
               PX2, 
               PX3, 
               X1,
               X2, 
               X3, 
               X, 
               PDSI, 
               PHDI, 
               WPLM, 
               j, 
               m, 
               nendyr, 
               nbegyr, 
               SX1, 
               SX2, 
               SX3, 
               SX, 
               indexj, 
               indexm,
               Z):

    #-----------------------------------------------------------------------
    #     PROB(END) RETURNS TO 0.  A POSSIBLE ABATEMENT HAS FIZZLED OUT,
    #     SO WE ACCEPT ALL STORED VALUES OF X3  
    #-----------------------------------------------------------------------
    PV = 0.0 
    PX1[j, m] = 0.0 
    PX2[j, m] = 0.0 
    PPR[j, m] = 0.0 
    PX3[j, m] = 0.897 * X3 + Z[j, m] / 3.0
    X[j, m]   = PX3[j, m] 
    if (K8 == 1): 
        PDSI[j, m] = X[j, m]  
        PHDI[j, m] = PX3[j, m] 
        if PX3[j, m] ==  0.0:
            PHDI[j, m] = X[j, m]
        case(PPR[j, m], PX1[j, m], PX2[j, m], PX3[j, m], WPLM[j, m]) 
    else:
        iass = 3   
        assign(iass, K8, PPR, PX1, PX2, PX3, X, PDSI, PHDI, WPLM, j, m, nendyr, nbegyr, SX1, SX2, SX3, SX, indexj, indexm)

    #-----------------------------------------------------------------------
    #     SAVE THIS MONTHS CALCULATED VARIABLES (V,PRO,X1,X2,X3) FOR   
    #     USE WITH NEXT MONTHS DATA 
    #-----------------------------------------------------------------------
    V = PV 
#     eff[j, m] = PV 
    PRO = PPR[j, m] 
    X1  = PX1[j, m] 
    X2  = PX2[j, m] 
    X3  = PX3[j, m] 

    return X, X1, X2, X3, SX1, SX2, SX3, V, PRO, K8

#-----------------------------------------------------------------------------------------------------------------------
def assign(iass,
           k8,
           PPR,
           PX1,
           PX2,
           PX3,
           X,
           PDSI,
           PHDI,
           WPLM,
           j,
           m,
           nendyr,
           nbegyr,
           SX1,
           SX2,
           SX3,
           SX,
           indexj,
           indexm):

    '''
      
    :param sx1: ndarray with 40 elements
    :param sx2: ndarray with 40 elements
    :param sx3: ndarray with 40 elements
    :param sx: ndarray with 96 elements
    :param pdsi: ndarray with shape (200, 13)
    :param phdi: ndarray with shape (200, 13)
    :param wplm: ndarray with shape (200, 13)
    :param ppr: ndarray with shape (200, 12)
    :param px1: ndarray with shape (200, 12)
    :param px2: ndarray with shape (200, 12)
    :param px3: ndarray with shape (200, 12)
    :param x: ndarray with shape (200, 12)
    :param indexj: ndarray with 40 elements
    :param indexm: ndarray with 40 elements
     '''
    #   
    #-----------------------------------------------------------------------
    #     FIRST FINISH OFF FILE 8 WITH LATEST VALUES OF PX3, Z,X
    #     X=PX1 FOR I=1, PX2 FOR I=2, PX3,  FOR I=3 
    #-----------------------------------------------------------------------
    SX[k8] = X[j, m] 
    ISAVE = iass
    if k8 == 1:
        PDSI[j, m] = X[j, m]  
        PHDI[j, m] = PX3[j, m] 
        if PX3[j, m] == 0.0:
            PHDI[j, m] = X[j, m]
        case(PPR[j, m], PX1[j, m], PX2[j, m], PX3[j, m], WPLM[j, m]) 
        return

    if iass == 3:  
        #     ---------------- USE ALL X3 VALUES
        for Mm in range(k8):
    
            SX[Mm] = SX3[Mm]

    else: 
        #     -------------- BACKTRACK THRU ARRAYS, STORING ASSIGNED X1 (OR X2) 
        #                    IN SX UNTIL IT IS ZERO, THEN SWITCHING TO THE OTHER
        #                    UNTIL IT IS ZERO, ETC. 
        for Mm in range(k8, 0, -1):
            
            if SX1[Mm] == 0:
                ISAVE = 2 
                SX[Mm] = SX2[Mm]
            else:
                ISAVE = 1 
                SX[Mm] = SX1[Mm]

    #-----------------------------------------------------------------------
    #     PROPER ASSIGNMENTS TO ARRAY SX HAVE BEEN MADE,
    #     OUTPUT THE MESS   
    #-----------------------------------------------------------------------

    for n in range(k8):
        
        PDSI[indexj[n], indexm[n]] = SX[n] 
        PHDI[indexj[n], indexm[n]] = PX3[indexj[n], indexm[n]]
        
        if (PX3[indexj[n], indexm[n]] == 0.0):
            PHDI[indexj[n], indexm[n]] = SX[n]
            
        case(PPR[indexj[n], indexm[n]],
             PX1[indexj[n], indexm[n]], 
             PX2[indexj[n], indexm[n]],
             PX3[indexj[n], indexm[n]],
             WPLM[indexj[n], indexm[n]])

    k8 = 1
    k8max = k8

    return

#-----------------------------------------------------------------------------------------------------------------------
def case(PROB,
         X1,
         X2,
         X3):
    #   
    #     THIS SUBROUTINE SELECTS THE PRELIMINARY (OR NEAR-REAL TIME)   
    #     PALMER DROUGHT SEVERITY INDEX (PDSI) FROM THE GIVEN X VALUES  
    #     DEFINED BELOW AND THE PROBABILITY (PROB) OF ENDING EITHER A   
    #     DROUGHT OR WET SPELL. 
    #   
    #     X1   - INDEX FOR INCIPIENT WET SPELLS (ALWAYS POSITIVE)   
    #     X2   - INDEX FOR INCIPIENT DRY SPELLS (ALWAYS NEGATIVE)   
    #     X3   - SEVERITY INDEX FOR AN ESTABLISHED WET SPELL (POSITIVE) OR DROUGHT (NEGATIVE)  
    #     PALM - THE SELECTED PDSI (EITHER PRELIMINARY OR FINAL)
    #   
    #   This subroutine written and provided by CPC (Tom Heddinghaus & Paul Sabol).
    #   

    if X3 == 0.0: #) GO TO 10 in pdinew.f
        #     IF X3=0 THE INDEX IS NEAR NORMAL AND EITHER A DRY OR WET SPELL
        #     EXISTS.  CHOOSE THE LARGEST ABSOLUTE VALUE OF X1 OR X2.  
        PALM = X1
        if abs(X2) > abs(X1): 
            PALM = X2

    elif  PROB > 0.0 and PROB < 100.0: # GO TO 20 in pdinew.f

        # put the probability value into 0..1 range
        PRO = PROB / 100.0
        if X3 > 0.0: #) GO TO 30
            #     TAKE THE WEIGHTED SUM OF X3 AND X2
            PALM = (1.0 - PRO) * X3 + PRO * X2   
        else:  
            #     TAKE THE WEIGHTED SUM OF X3 AND X1
            PALM = (1.0 - PRO) * X3 + PRO * X1   

    else:
        #     A WEATHER SPELL IS ESTABLISHED AND PALM=X3 AND IS FINAL
        PALM = X3
 
    return PALM

#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def z_index(P,
            PET,
            ET,
            PR,
            R,
            RO,
            PRO,
            L,
            PL,
            data_start_year,
            calibration_start_year,
            calibration_end_year):
    '''
    This function calculates Palmer's Z index using inputs from the water balance function.
    
    :param P: 1-D numpy.ndarray of monthly precipitation observations, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PET: 1-D numpy.ndarray of monthly potential evapotranspiration values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param ET: 1-D numpy.ndarray of monthly evapotranspiration values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PR: 1-D numpy.ndarray of monthly potential recharge values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param R: 1-D numpy.ndarray of monthly recharge values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param RO: 1-D numpy.ndarray of monthly runoff values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PRO: 1-D numpy.ndarray of monthly potential runoff values, in inches, the number of array elements 
                (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param L: 1-D numpy.ndarray of monthly loss values, in inches, the number of array elements 
              (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param PL: 1-D numpy.ndarray of monthly potential loss values, in inches, the number of array elements 
               (array size) should be a multiple of 12 (representing an ordinal number of full years)
    :param data_start_year: initial year of the input arrays, i.e. the first element of each of the input arrays 
                            is assumed to correspond to January of this initial year
    :param calibration_start_year: initial year of the calibration period, should be greater than or equal to the data_start_year
    :param calibration_end_year: final year of the calibration period
    :return 1-D numpy.ndarray of Z-Index values, with shape corresponding to the input arrays
    :rtype: numpy.ndarray of floats
    '''
    
    # the potential (PET, ET, PR, PL) and actual (R, RO, S, L, P) water balance arrays are reshaped as 2-D arrays  
    # (matrices) such that the rows of each matrix represent years and the columns represent calendar months
    PET = utils.reshape_to_years_months(PET)
    ET = utils.reshape_to_years_months(ET)
    PR = utils.reshape_to_years_months(PR)
    PL = utils.reshape_to_years_months(PL)
    R = utils.reshape_to_years_months(R)
    RO = utils.reshape_to_years_months(RO)
    PRO = utils.reshape_to_years_months(PRO)
    L = utils.reshape_to_years_months(L)
    P = utils.reshape_to_years_months(P)
        
    # ALPHA, BETA, GAMMA, DELTA CALCULATIONS
    # A calibration period is used to calculate alpha, beta, gamma, and 
    # and delta, four coefficients dependent on the climate of the area being
    # examined. The NCDC and CPC use the calibration period January 1931
    # through December 1990 (cf. Karl, 1986; Journal of Climate and Applied 
    # Meteorology, Vol. 25, No. 1, January 1986).
    
    #!!!!!!!!!!!!!
    # TODO make sure calibration years range is valid, i.e. within actual data years range 
    
    # determine the array (year axis) indices for the calibration period
    total_data_years = int(P.shape[0] / 12)
    data_end_year = data_start_year + total_data_years - 1
    total_calibration_years = calibration_end_year - calibration_start_year + 1
    calibration_start_year_index = calibration_start_year - data_start_year
    calibration_end_year_index = calibration_end_year - data_start_year 
    
    # get calibration period arrays
    if (calibration_start_year > data_start_year) or (calibration_end_year < data_end_year):
        P_calibration = P[calibration_start_year_index:calibration_end_year_index + 1]
        ET_calibration = ET[calibration_start_year_index:calibration_end_year_index + 1]
        PET_calibration = PET[calibration_start_year_index:calibration_end_year_index + 1]
        R_calibration = R[calibration_start_year_index:calibration_end_year_index + 1]
        PR_calibration = PR[calibration_start_year_index:calibration_end_year_index + 1]
        L_calibration = L[calibration_start_year_index:calibration_end_year_index + 1]
        PL_calibration = PL[calibration_start_year_index:calibration_end_year_index + 1]
        RO_calibration = RO[calibration_start_year_index:calibration_end_year_index + 1]
        PRO_calibration = PRO[calibration_start_year_index:calibration_end_year_index + 1]
    else:
        P_calibration = P
        ET_calibration = ET
        PET_calibration = PET
        R_calibration = R
        PR_calibration = PR
        L_calibration = L
        PL_calibration = PL
        RO_calibration = RO
        PRO_calibration = PRO

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        
        # get averages for each calendar month (compute means over the year axis, giving an average for each calendar month over all years)
        P_bar = np.nanmean(P_calibration, axis=0)
        ET_bar = np.nanmean(ET_calibration, axis=0)
        PET_bar = np.nanmean(PET_calibration, axis=0)
        R_bar = np.nanmean(R_calibration, axis=0)
        PR_bar = np.nanmean(PR_calibration, axis=0)
        L_bar = np.nanmean(L_calibration, axis=0)
        PL_bar = np.nanmean(PL_calibration, axis=0)
        RO_bar = np.nanmean(RO_calibration, axis=0)
        PRO_bar = np.nanmean(PRO_calibration, axis=0)
            
        # TODO document the significance of these arrays
        alpha = np.empty((12,))
        beta = np.empty((12,))
        gamma = np.empty((12,))
        delta = np.empty((12,))
    
        # compute the alpha, beta, gamma, and delta coefficients for each calendar month
        for i in range(12):
            
            # calculate alpha
            if PET_bar[i] == 0:
                if ET_bar[i] == 0:
                    alpha[i] = 1
                else:
                    alpha[i] = 0
                    #logger.warn('CHECK DATA: PET is less than ET.')
            else:
                alpha[i] = ET_bar[i] / PET_bar[i]
    
            # calculate beta
            if PR_bar[i] == 0:
                if R_bar[i] == 0:
                    beta[i] = 1
                else:
                    beta[i] = 0
                    #logger.warn('CHECK DATA: PR is less than R.')
            else:
                beta[i] = R_bar[i] / PR_bar[i]
    
            # calculate gamma
            if PRO_bar[i] == 0:
                if RO_bar[i] == 0:
                    gamma[i] = 1
                else:
                    gamma[i] = 0
                    #logger.warn('CHECK DATA: PRO is less than RO.')
            else:
                gamma[i] = RO_bar[i] / PRO_bar[i]
    
            # calculate delta
            if PL_bar[i] == 0:
                if L_bar[i] == 0:
                    delta[i] = 1
                else:
                    delta[i] = 0
                    #logger.warn('CHECK DATA: PL is less than L.')
            else:
                delta[i] = L_bar[i] / PL_bar[i]
        
        # CALIBRATED CAFEC, K, AND d CALCULATION
        # NOTE: 
        # The Z index is calculated with a calibrated K (weighting factor) but
        # a full record d (difference between actual precipitation and CAFEC -
        # climatically appropriate for existing conditions - precipitation).
        # CAFEC precipitation is calculated analogously to a simple water
        # balance, where precipitation is equal to evaporation plus runoff 
        # (and groundwater recharge) plus or minus any change in soil moisture storage. 
        CAFEC_hat = np.empty((total_calibration_years, 12)) 
        d_hat = np.empty((total_calibration_years, 12)) 
        for k in range(total_calibration_years):
            for i in range(12):
                # CAFEC_hat is calculated for month i of year k of the calibration period.
                CAFEC_hat[k, i] = (alpha[i] * PET_calibration[k, i]) + \
                                  (beta[i] * PR_calibration[k, i]) + \
                                  (gamma[i] * PRO_calibration[k, i]) - \
                                  (delta[i] * PL_calibration[k, i])
                                  
                # Calculate d_hat, the difference between actual precipitation
                # and CAFEC precipitation for month i of year k of the calibration period.
                d_hat[k, i] = P_calibration[k, i] - CAFEC_hat[k, i]
        
        # NOTE: D_hat, T_hat, K_hat, and z_hat are all calibrated
        # variables - i.e., they are calculated only for the calibration period.
        D_hat = np.empty((12,)) 
        T_hat = np.empty((12,)) 
        K_hat = np.empty((12,)) 
        z_hat_m = np.empty((12,)) 
        for i in range(12):
                        
            # Calculate D_hat, the average of the absolute values of d_hat for month i.
            D_hat[i] = np.nanmean(np.absolute(d_hat[:, i]))
    
            # Calculate T_hat, a measure of the ratio of "moisture demand" to "moisture supply" for month i
            #TODO if this value evaluates to a negative number less than -2.8 then the following equation for K_hat 
            # will result in a math domain error -- is it valid here to limit this value to -2.8 or greater? 
            T_hat[i] = (PET_bar[i] + R_bar[i] + RO_bar[i]) / (P_bar[i] + L_bar[i])
            
            # Calculate K_hat, the denominator of the K equation for month i.
            # from figure 3, Palmer 1965
            K_hat[i] = 1.5 * math.log10((T_hat[i] + 2.8) / D_hat[i]) + .50
            
            # Calculate z_hat, the numerator of the K equation for month i.
            z_hat_m[i] = D_hat[i] * K_hat[i]
        
        z_hat = sum(z_hat_m)
    
    # Calculate the weighting factor, K, using the calibrated variables K_hat and z_hat. The purpose of
    # the weighting factors is to adjust the  departures from normal precipitation d (calculated below), 
    # such that they are comparable among different locations and for different months. The K tends to be
    # large in arid regions and small in humid regions (cf. Alley, 1984; Journal of Climate and Applied Meteorology, 
    # Vol. 23, No. 7, July 1984).
    K = np.empty((12,)) 
    for i in range(12):
        K[i] = (17.67 * K_hat[i]) / z_hat
    
    # FULL RECORD CAFEC AND d CALCULATION
    CAFEC = np.empty((P.shape[0], 12))
    z = np.empty((P.shape[0], 12))
    for n in range(P.shape[0]):
        for i in range(12):
            # Calculate the CAFEC precipitation for month i and year n of the full record.
            CAFEC[n, i] = (alpha[i] * PET[n, i]) + \
                          (beta[i] * PR[n, i]) + \
                          (gamma[i] * PRO[n, i]) - \
                          (delta[i] * PL[n, i])
            
            # Calculate d_hat, difference between actual precipitation and
            # CAFEC precipitation for month i and year n of the full record.
            difference = P[n, i] - CAFEC[n, i]
            
            # Calculate the Z index or the "moisture anomaly index" for 
            # month i and year n of the full record.
            z[n, i] = K[i] * difference

    return z.flatten()

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT):

    # This function calculates PX1 and PX2 and calls the backtracking loop.
    # If the absolute value of PX1 or PX2 goes over 1, that value becomes the new PX3. 
    
    # Calculate the current PX1 and PX2.
    PX1[k] = max(0.0, 0.897 * X1 + (Z[k] / 3))
    PX2[k] = min(0.0, 0.897 * X2 + (Z[k] / 3))
    
    if (PX1[k] >= 1) and (PX3[k] == 0):
        # When PX1 >= 1 the wet spell becomes established. X is assigned as PX1
        # and PX3 = PX1. PX1 is set to zero after PX3 is set to PX1. BT is set
        # to 1 and the backtrack function is called to begin backtracking up
        # PX1.
        X[k] = PX1[k]              
        PX3[k] = PX1[k]            
        PX1[k] = 0
        BT[k] = 1
        X, BT = BackTrack(k, PPe, PX1, PX2, PX3, X, BT)                                                             
    
    elif (PX2[k] <= -1) and (PX3[k] == 0):
        # When PX2 <= -1 the drought becomes established. X is assigned as PX2
        # and PX3 = PX2. PX2 is set to zero after PX3 is set to PX2. BT is set
        # to 2 and the backtrack function is called to begin backtracking up PX2.
        X[k] = PX2[k]
        PX3[k] = PX2[k]
        PX2[k] = 0
        BT[k] = 2
        X, BT = BackTrack(k, PPe, PX1, PX2, PX3, X, BT)                                                             
    
    elif PX3[k] == 0:
        # When PX3 is zero and both |PX1| and |PX2| are less than 1, there is
        # no established drought or wet spell. X is set to whatever PX1 or PX2
        # value is not equal to zero. BT is set to either 1 or 2 depending on
        # which PX1 or PX2 value equals zero. The backtrack function is called
        # to begin backtracking up either PX1 or PX2 depending on the BT value.
        if PX1[k] == 0:
        
            X[k] = PX2[k]
            BT[k] = 2
            X, BT = BackTrack(k, PPe, PX1, PX2, PX3, X, BT)                                                                 

        elif PX2[k] == 0:
            
            X[k] = PX1[k]
            BT[k] = 1
            X, BT = BackTrack(k, PPe, PX1, PX2, PX3, X, BT)                                                          
    else:
        # There is no determined value to assign to X when PX3 ~= 0, 
        # 0 <= PX1 < 1, and -1 < PX2 <= 0 so set X = PX3.   
        X[k] = PX3[k]

    return PX1, PX2, PX3, X, BT

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def BackTrack(k, PPe, PX1, PX2, PX3, X, BT):

    # This function backtracks through previous PX1 and PX2 values.
    # Backtracking occurs in two instances: (1) After the probability reaches 
    # 100 and (2) When the probability is zero. In either case, the
    # backtracking function works by backtracking through PX1 and PX2 until
    # reaching a month where PPe = 0. Either PX1 or PX2 is assigned to X as the
    # backtracking progresses.
    
    # Backtracking occurs from either PPe[k] = 100 or PPe[k] = 0 to the first 
    # instance in the previous record where PPe = 0. This "for" loop counts 
    # back through previous PPe values to find the first instance where PPe = 0.
    # r is a variable used to mark the place of the last PPe = 0 before PPe = 100.
    r = 0
    for c in range(k, 0, -1):
        if PPe[c] == 0:
            r = c
            break
    
    # Backtrack from either PPe = 100 or PPe = 0 to the last instance of 
    # non-zero, non-one hundred probability.
    for count in range(k, r, -1):
        # When PPe[k] = 100 and |PX3| > 1 set X[k] = PX3[k].
        #                                                                       
        # Set the BT value of the previous month to either 1 or 2 based on the
        # sign of PX3[k]. If PX3[k] is negative, a BT = 2 begins backtracking 
        # up X2 and vice versa.
        if (PPe[count] == 100) and (abs(PX3[count]) > 1):
            X[count] = PX3[count]
            if PX3[count] < 0:
                BT[count - 1] = 2
            else:
                BT[count - 1] = 1
        
        # Everything below deals with months where PPe is not equal to 100. 
        # Based on the assigned BT value, start in either PX1 or PX2. If
        # that value is not 0, assign X and set the BT value for the preceding
        # month to 1 if X = PX1 or 2 if X = PX2. If BT = 1 and PX1 = 0, assign 
        # X to PX2 and set the BT value for the preceding month to 2 and vice
        # versa. Continue this process of backtracking up either PX1 or PX2
        # and switching when either PX1 or PX2 equals 0 or until the end of the
        # loop is reached.
        elif BT[count] == 2:
            if PX2[count] == 0:
                X[count] = PX1[count]
                BT[count] = 1
                BT[count - 1] = 1
            else:
                X[count] = PX2[count]
                BT[count - 1] = 2
        elif BT[count] == 1:
            if PX1[count] == 0:
                X[count] = PX2[count]
                BT[count] = 2
                BT[count - 1] = 2
            else:
                X[count] = PX1[count]
                BT[count - 1] = 1
    
    return X, BT

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X):

    # This function is called when non-zero, non-one hundred PPe values occur
    # between values of PPe = 0. When this happens, a possible abatement
    # discontinues without ending the wet spell or drought. X should be
    # assigned to PX3 for all months between, and including, the two instances
    # of PPe = 0 (cf. Alley, 1984; Journal of Climate and Applied Meteorology, 
    # Vol. 23, No. 7). To do this, backtrack up to the first instance of 
    # PPe = 0 while setting X to PX3. 
    
    # Since the possible abatement has ended, the drought or wet spell
    # continues. Set PV, PX1, PX2, and PPe to 0. Calculate PX3 and set X = PX3.
    # Set BT=3 in preparation for backtracking.
    PV = 0                         
    PX1[k] = 0                     
    PX2[k] = 0                     
    PPe[k] = 0                     
    PX3[k] = 0.897 * X3 + (Z[k] / 3)
    X[k] = PX3[k]
    BT[k] = 3
    
    # In order to set all values of X between the two instances of PPe = 0, the
    # first instance of PPe = 0 must be found. This "for" loop counts back 
    # through previous PPe values to find the first instance where PPe = 0.
    for count1 in range(k, 0, -1):
        if PPe[count1] == 0:
            r = count1
            break
    
    # Backtrack from the current month where PPe = 0 to the last month where PPe = 0.
    for count in range(k, r - 1, -1):
        # Set X = PX3
        if BT[count] == 3:
            X[count] = PX3[count]
            # If the end of the backtracking loop hasn't been reached, set the
            # BT value for the preceding month to 3 to continue the backtracking.
            if count != r:
                BT[count - 1] = 3

    return PV, PX1, PX2, PX3, PPe, X, BT

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def Function_Uw(k, Uw, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT):

    # In the case of an established drought, Palmer (1965) notes that a value of Z = -0.15 will maintain an
    # index of -0.50 from month to month. An established drought or wet spell is considered definitely over
    # when the index reaches the "near normal" category which lies between -0.50 and +0.50. Therefore, any
    # value of Z >= -0.15 will tend to end a drought.
    Uw[k] = Z[k] + 0.15 
    
    PV = Uw[k] + max(V, 0)
    if PV <= 0:
        # During a drought, PV <= 0 implies PPe = 0 (i.e., the 
        # probability that the drought has ended returns to zero).                                                             
        Q = 0 
        PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)                                                                 
    
    else:
        Ze[k] = -2.691 * X3 - 1.5
        if Pe == 100: 
            Q = Ze[k]  # Q is the total moisture anomaly required to end the current drought.
        else:
            Q = Ze[k] + V

        PPe[k] = (PV / Q) * 100
    
        if PPe[k] >= 100:
            PPe[k] = 100
            PX3[k] = 0
        else:
            PX3[k] = 0.897 * X3 + (Z[k] / 3)

        PX1, PX2, PX3, X, BT = Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT)                                                                 

    return Uw, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def Function_Ud(k, Ud, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT):

    # In the case of an established wet spell, Palmer (1965) notes that a value of Z = +0.15 will maintain an index of +0.50 
    # from month to month. An established drought or wet spell is considered definitely over when the index reaches the "near 
    # normal" category which lies between -0.50 and +0.50. Therefore, any value of Z <= +0.15 will tend to end a wet spell.
    Ud[k] = Z[k] - 0.15
    
    PV = Ud[k] + min(V, 0)
    if PV >= 0: 
        # During a wet spell, PV >= 0 implies PPe = 0 (i.e., the 
        # probability that the wet spell has ended returns to zero).
        Q = 0 
        PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)                                                           
    
    else:
        Ze[k] = -2.691 * X3 + 1.5
        if Pe == 100:
            Q = Ze[k]      # Q is the total moisture anomaly required to end the current wet spell.
        else:
            Q = Ze[k] + V

        PPe[k] = (PV / Q) * 100
        if PPe[k] >= 100:
            PPe[k] = 100
            PX3[k] = 0
        else:
            PX3[k] = 0.897 * X3 + (Z[k] / 3)

        PX1, PX2, PX3, X, BT = Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT)                                                                 

    return Ud, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def _compute_X(established_index_values,
             sczindex_values,
             scpdsi_values,
             pdsi_values,
             wet_index_values,
             dry_index_values,
             wet_index_deque,
             dry_index_deque,
             wetM,
             wetB,
             dryM,
             dryB,
             calibration_complete,
             tolerance=0.0):
    '''
    This function computes X values
    :param established_index_values
    :param sczindex_values
    :param scpdsi_values
    :param pdsi_values
    :param wet_index_values
    :param dry_index_values
    :param wet_index_deque
    :param dry_index_deque
    :param wetM
    :param wetB
    :param dryM
    :param dryB
    :param calibration_complete
    :param tolerance
     '''
    # empty all X lists
    wet_index_deque.clear()
    dry_index_deque.clear()

    # Initializes the book keeping indices used in finding the PDSI
    _dblV = 0.0
    _dblQ = 0.0

    period = 0
    prvKey = -1

    for period in range(established_index_values.size):
    
        # These variables represent the values for  corresponding variables for the current period.
        # They are kept separate because many calculations depend on last period's values.  
#         newV
#         newProb
        newX = 0
        newX1 = 0
        newX2 = 0
        newX3 = 0
        previousEstablishedIndexX3 = 0

#         # ZE is the Z value needed to end an established spell
#         ZE
#         m
#         b
#         c
# 
#         # wd is a sign changing flag.  It allows for use of the same equations during both a wet or dry spell by adjusting the appropriate signs.
#         wd

        if (prvKey >= 0) and not np.isnan(established_index_values[prvKey]):
        
            previousEstablishedIndexX3 = established_index_values[prvKey]

        if previousEstablishedIndexX3 >= 0:
        
            m = wetM
            b = wetB
        
        else:
        
            m = dryM
            b = dryB
        
        if not np.isnan(sczindex_values[period]) and ((m + b) != 0):

            c = 1 - (m / (m + b))

            # This sets the wd flag by looking at EstablishedIndex
            if previousEstablishedIndexX3 >= 0:
                wd = 1
            else:
                wd = -1

            # If EstablishedIndex is 0 then there is no reason to calculate Q or ZE, V and Prob are reset to 0;
            if previousEstablishedIndexX3 == 0:
            
                newX3 = 0
                newV = 0
                newProb = 0
                newX, newX1, newX2, newX3 = chooseX(pdsi_values,
                                                    established_index_values,
                                                    wet_index_values,
                                                    dry_index_values,
                                                    sczindex_values,
                                                    wet_index_deque,
                                                    dry_index_deque,
                                                    wetM,
                                                    wetB,
                                                    dryM,
                                                    dryB,
                                                    newX, 
                                                    newX1, 
                                                    newX2, 
                                                    newX3, 
                                                    period, 
                                                    prvKey)

            # Otherwise all calculations are needed.
            else:
                                
                newX3 = (c * previousEstablishedIndexX3 + sczindex_values[period] / (m + b))
                # ZE is the Z value needed to end an established spell
                ZE = (m + b) * (wd * 0.5 - c * previousEstablishedIndexX3)
                _dblQ = ZE + _dblV
                newV = sczindex_values[period] - wd * (m * 0.5) + wd * min(wd * _dblV + tolerance, 0)

                if (wd * newV) > 0:
                
                    newV = 0
                    newProb = 0
                    newX1 = 0
                    newX2 = 0
                    newX = newX3

                    wet_index_deque.clear()
                    dry_index_deque.clear()
                
                else:

                    newProb = (newV / _dblQ) * 100;
                    if newProb >= (100 - tolerance):

                        newX3 = 0
                        newV = 0
                        newProb = 100

                    # xValues should be a list of doubles
                    newX, newX1, newX2, newX3 = chooseX(pdsi_values,
                                                        established_index_values,
                                                        wet_index_values,
                                                        dry_index_values,
                                                        sczindex_values,
                                                        wet_index_deque,
                                                        dry_index_deque,
                                                        wetM,
                                                        wetB,
                                                        dryM,
                                                        dryB,
                                                        newX, 
                                                        newX1, 
                                                        newX2, 
                                                        newX3, 
                                                        period, 
                                                        prvKey)

            wet_index_values[period] = newX1
            dry_index_values[period] = newX2
            established_index_values[period] = newX3
            
            if calibration_complete:
                scpdsi_values[period] = newX
            else:
                pdsi_values[period] = newX
            
            # update variables for next month:
            _dblV = newV
        
        else:
        
            # This month's data is missing, so output MISSING as PDSI.  All variables used in calculating the PDSI are kept from the previous month.  
            # Only the linked lists are changed to make sure that if backtracking occurs, a MISSING value is kept as the PDSI for this month.
            pdsi_values[period] = np.NaN
            wet_index_values[period] = np.NaN
            dry_index_values[period] = np.NaN
            established_index_values[period] = np.NaN
            if calibration_complete:
                scpdsi_values[period] = np.NaN
            else:
                pdsi_values[period] = np.NaN

        prvKey = period
        period += 1

    return pdsi_values, scpdsi_values, wet_index_values, dry_index_values, established_index_values

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def chooseX(pdsi_values,
            established_index_values,
            wet_index_values,
            dry_index_values,
            sczindex_values,
            wet_index_deque,
            dry_index_deque,
            wetM,
            wetB,
            dryM,
            dryB,
            newX, 
            newX1, 
            newX2, 
            newX3, 
            period, 
            prvKey,
            tolerance=0.0):

    previousWetIndexX1 = 0
    previousDryIndexX2 = 0

    if (prvKey >= 0) and not np.isnan(established_index_values[prvKey]):
    
        previousWetIndexX1 = wet_index_values[prvKey]
        previousDryIndexX2 = dry_index_values[prvKey]
    
    wetc = 1 - (wetM / (wetM + wetB))
    dryc = 1 - (dryM / (dryM + dryB))

    zIndex = sczindex_values[period]
    newX1 = (wetc * previousWetIndexX1 + zIndex / (wetM + wetB))
    if newX1 < 0:
    
        newX1 = 0.0
    
    newX2 = (dryc * previousDryIndexX2 + zIndex / (dryM + dryB))
    if newX2 > 0:
    
        newX2 = 0.0

    if (newX1 >= 0.5) and (newX3 == 0):
    
        backtrack(pdsi_values,
                  wet_index_deque,
                  dry_index_deque,
                  tolerance,
                  newX1, 
                  newX2, 
                  period)
        newX = newX1
        newX3 = newX1
        newX1 = 0.0
    
    else:
    
        newX2 = dryc * previousDryIndexX2 + zIndex / (dryM + dryB)
        if newX2 > 0:
        
            newX2 = 0.0
        
        if (newX2 <= -0.5) and (newX3 == 0):
        
            backtrack(pdsi_values,
                      wet_index_deque,
                      dry_index_deque,
                      tolerance,
                      newX2, 
                      newX1, 
                      period)
            newX = newX2
            newX3 = newX2
            newX2 = 0.0
        
        elif newX3 == 0:
        
            if newX1 == 0:
            
                backtrack(pdsi_values,
                          wet_index_deque,
                          dry_index_deque,
                          tolerance,
                          newX2, 
                          newX1, 
                          period)
                newX = newX2
            
            elif newX2 == 0:
            
                backtrack(pdsi_values,
                          wet_index_deque,
                          dry_index_deque,
                          tolerance,
                          newX1, 
                          newX2, 
                          period)
                newX = newX1
            
            else:
            
                wet_index_deque.appendleft(newX1)
                dry_index_deque.appendleft(newX2)
                newX = newX3
        
        else:
        
            # store WetIndex and DryIndex in their linked lists for possible use later
            wet_index_deque.appendleft(newX1)
            dry_index_deque.appendleft(newX2)
            newX = newX3
    
    return newX, newX1, newX2, newX3

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def backtrack(pdsi_values,
              wet_index_deque,
              dry_index_deque,
              tolerance,
              X1, 
              X2, 
              thePeriod):
    '''
    :param computationFrame
    :param X1
    :param X2
    :param thePeriod
    '''
    
    num1 = X1

    while (len(wet_index_deque) > 0) and (len(dry_index_deque) > 0):
    
        if num1 > 0:
        
            num1 = wet_index_deque.popleft()
            num2 = dry_index_deque.popleft()
        
        else:
        
            num1 = dry_index_deque.popleft()
            num2 = wet_index_deque.popleft()

        if ((-1.0 * tolerance) <= num1) and (num1 <= tolerance):
        
            num1 = num2
        
        pdsi_values[thePeriod] = num1

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def _z_sum(interval, 
           wet_or_dry,
           sczindex_values,
           periods_per_year,
           calibration_start_year,
           calibration_end_year,
           input_start_year):

        z = 0.0
        z_temporary = deque()
        values_to_sum = deque()
        summed_values = deque()
        
        # get only non-NaN Z-index values
        for sczindex in sczindex_values:
        
            # we need to skip Z-index values from the list if they don't exist, this can result from empty months in the final year of the data set
            if not np.isnan(sczindex):
            
                z_temporary.append(sczindex)
                
        calibration_period_initial_index = (calibration_start_year - input_start_year) * periods_per_year
        i = 0
        while (i < calibration_period_initial_index) and (len(z_temporary) > 0):
            
            # remove periods before the start of the calibration interval
            z_temporary.pop()
            i += 1

        remaining_calibration_periods = (calibration_end_year - calibration_start_year + 1) * periods_per_year

        # get the first interval length of values from the end of the calibration period working backwards, creating the first sum of interval periods
        sum_value = 0.0
        for i in range(interval):
        
            if len(z_temporary) == 0:
               
                i = interval
                
            else:

                # pull a value off the end of the list
                z = z_temporary.pop()
                remaining_calibration_periods -= 1
                
                if not np.isnan(z):
                
                    # add to the sum
                    sum_value += z
                    
                    # add to the array of values we've used for the initial sum
                    values_to_sum.appendleft(z)
                
                else:

                    # reduce the loop counter so we don't skip a calibration interval period
                    i -= 1
        
        # if we're dealing with wet conditions then we want to be using positive numbers, and if dry conditions  
        # then we need to be using negative numbers, so we introduce a sign variable to help with this 
        sign = 1
        if 'DRY' == wet_or_dry:

            sign = -1
        
        # for each remaining Z value, recalculate the sum of Z values
        largest_sum = sum_value
        summed_values.appendleft(sum_value)
        while (len(z_temporary) > 0) and (remaining_calibration_periods > 0):
        
            # take the next Z-index value off the end of the list 
            z = z_temporary.pop()

            # reduce by one period for each removal
            remaining_calibration_periods -= 1
        
            if not np.isnan(z):

                # come up with a new Z sum for this new group of Z values to sum
                
                # remove the last value from both the sum_value and the values to sum array
                sum_value -= values_to_sum.pop()
                
                # add to the Z sum, update the bookkeeping lists
                sum_value += z
                values_to_sum.append(z)
                summed_values.append(sum_value)
             
            # update the largest sum value
            if (sign * sum_value) > (sign * largest_sum):

                largest_sum = sum_value

        # Determine the highest or lowest reasonable value that isn't due to a freak anomaly in the data. 
        # A "freak anomaly" is defined as a value that is either
        #   1) 25% higher than the 98th percentile
        #   2) 25% lower than the 2nd percentile
        reasonable_percentile_index = 0
        if 'WET' == wet_or_dry:

            reasonable_percentile_index = int(len(summed_values) * 0.98)

        else:  # DRY
        
            reasonable_percentile_index = int(len(summed_values) * 0.02)
        
        # sort the list of sums into ascending order and get the sum_value value referenced by the safe percentile index
        summed_values = sorted(summed_values)
        sum_at_reasonable_percentile = summed_values[reasonable_percentile_index]
          
        # find the highest reasonable value out of the summed values
        highest_reasonable_value = 0.0
        reasonable_tolerance_ratio = 1.25
        while len(summed_values) > 0:

            sum_value = summed_values.pop()
            if (sign * sum_value) > 0:

                if (sum_value / sum_at_reasonable_percentile) < reasonable_tolerance_ratio:
                
                    if (sign * sum_value) > (sign * highest_reasonable_value):
                    
                        highest_reasonable_value = sum_value
        
        if 'WET' == wet_or_dry:
        
            return highest_reasonable_value
        
        else:  # DRY
        
            return largest_sum

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def _least_squares(x, 
                 y, 
                 n, 
                 wetOrDry):
    
        correlation = 0.0
        c_tol = 0.85
        max_value = 0.0
        max_diff = 0.0
        max_i = 0
        sumX = 0.0
        sumY = 0.0
        sumX2 = 0.0
        sumY2 = 0.0
        sumXY = 0.0
        for i in range(n):
        
            this_x = x[i]
            this_y = y[i]
            sumX += this_x
            sumY += this_y
            sumX2 += this_x * this_x
            sumY2 += this_y * this_y
            sumXY += this_x * this_y
        
        SSX = sumX2 - (sumX * sumX) / n
        SSY = sumY2 - (sumY * sumY) / n
        SSXY = sumXY - (sumX * sumY) / n
        if (SSX > 0) and (SSY > 0):  # perform this check to avoid square root of negative(s)
            correlation = SSXY / (math.sqrt(SSX) * math.sqrt(SSY))
        
        i = n - 1
        
        # if we're dealing with wet conditions then we want to be using positive numbers, and for dry conditions  
        # then we want to be using negative numbers, so we introduce a sign variable to facilitate this 
        sign = 1
        if 'DRY' == wetOrDry: 
            sign = -1     
        
        while ((sign * correlation) < c_tol) and (i > 3):
        
            # when the correlation is off, it appears better to
            # take the earlier sums rather than the later ones.
            this_x = x[i]
            this_y = y[i]
            sumX -= this_x
            sumY -= this_y
            sumX2 -= this_x * this_x
            sumY2 -= this_y * this_y
            sumXY -= this_x * this_y
            SSX = sumX2 - (sumX * sumX) / i
            SSY = sumY2 - (sumY * sumY) / i
            SSXY = sumXY - (sumX * sumY) / i
            if (SSX > 0) and (SSY > 0):  # perform this check to avoid square root of negative(s)
                correlation = SSXY / (math.sqrt(SSX) * math.sqrt(SSY))
            i -= 1
        
        leastSquaresSlope = SSXY / SSX
        for j in range(i + 1):
        
            if (sign * (y[j] - leastSquaresSlope * x[j])) > (sign * max_diff):
            
                max_diff = y[j] - leastSquaresSlope * x[j]
                max_i = j
                max_value = y[j]
             
        leastSquaresIntercept = max_value - leastSquaresSlope * x[max_i]
        
        return leastSquaresSlope, leastSquaresIntercept

#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def pdsi_from_zindex(Z):

    ## INITIALIZE PDSI AND PHDI CALCULATIONS
    
    # V is the sum of the Uw (Ud) values for the current and previous months of an
    # established dry (wet) spell and is used in calculating the Pe value for a month.
    V = 0.0
    Pe = 0.0 # Pe is the probability that the current wet or dry spell has ended in a month.
    X1 = 0.0 # X1 is the severity index value for an incipient wet spell for a month.
    X2 = 0.0 # X2 is the severity index value for an incipient dry spell for a month.
    X3 = 0.0 # X3 is the severity index value of the current established wet or dry spell for a month.
    Q = 0.0
    
    number_of_months = Z.shape[0]
    
    # BACTRACKING VARIABLES
    
    # BT is the backtracking variable, and is pre-allocated with zeros. Its value (1, 2, or 3) indicates which 
    # intermediate index (X1, X2, or X3) to backtrack up, selecting the associated term (X1, X2, or X3) for the PDSI. NOTE: BT may
    # be operationally left equal to 0, as it cannot be known in real time when an existing drought or wet spell may or may not be over.
    BT = np.zeros((number_of_months,)) 
    
    ## CALCULATE PDSI AND PHDI
    PX1 = np.zeros((number_of_months,))
    PX2 = np.zeros((number_of_months,))
    PX3 = np.zeros((number_of_months,))
    PPe = np.zeros((number_of_months,))
    X = np.zeros((number_of_months,))
    PMDI = np.zeros((number_of_months,))
    
    # Ze is the soil moisture anomaly (Z) value that will end the current established dry or wet spell in that 
    # month and is used in calculating the Q value and subsequently the Pe value for a month
    Ze = np.zeros((number_of_months,))
    
    # Uw is the effective wetness required in a month to end the current established dry spell (drought)
    Uw = np.zeros((number_of_months,))
    
    # Ud is the effective dryness required in a month to end the current wet spell
    Ud = np.zeros((number_of_months,))
    
    # Palmer Hydrological Drought Index
    PHDI = np.zeros((number_of_months,))

    # loop over all months in the dataset, calculating PDSI and PHDI for each
    for k in range(number_of_months):
        
        PMDI[k] = pmdi(Pe, X1, X2, X3)
        
        if (Pe == 100) or (Pe == 0):   # no abatement underway
            
            if abs(X3) <= 0.5:   # drought or wet spell ends
                
                # PV is the preliminary V value and is used in operational calculations.
                PV = 0 
                
                # PPe is the preliminary Pe value and is used in operational calculations.
                PPe[k] = 0 
                
                # PX3 is the preliminary X3 value and is used in operational calculations.
                PX3[k] = 0 
                                
                PX1, PX2, PX3, X, BT = Main(Z, k, PV, PPe, X1, X2, PX1, PX2, PX3, X, BT)
 
            elif X3 > 0.5: # Wet spell underway
                if Z[k] >= 0.15: # Wet spell intensifies
                    PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)                                                  
                else: # Wet spell starts to abate, and it may end.
                    Ud, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Ud(k, Ud, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                                                                                               
            elif X3 < -0.5: # Drought underway
                if Z[k] <= -0.15: # Drought intensifies 
                    PV, PX1, PX2, PX3, PPe, X, BT = Between0s(k, Z, X3, PX1, PX2, PX3, PPe, BT, X)                                                 
                else: # Drought starts to abate, and it may end.
                    Uw, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Uw(k, Uw, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                                                                                          
        else: # Abatement underway
            if X3 > 0: # Wet spell underway
                Ud, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Ud(k, Ud, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)                                                     
            else: # Drought underway
                Uw, Ze, Q, PV, PPe, PX1, PX2, PX3, X, BT = Function_Uw(k, Uw, Z, Ze, V, Pe, PPe, PX1, PX2, PX3, X1, X2, X3, X, BT)
                                                                                                    
        ## Assign V, Pe, X1, X2, and X3 for next month (k + 1)
        V = PV
        Pe = PPe[k]
        X1 = PX1[k]
        X2 = PX2[k]
        X3 = PX3[k]
        
        ## ASSIGN X FOR CASES WHERE PX3 AND BT EQUAL ZERO
        # NOTE: This is a conflicting case that arises where X cannot be
        # assigned as X1, X2, or X3 in real time. Here 0 < PX1 < 1, 
        # -1 < PX2 < 0, and PX3 = 0, and it is not obvious which
        # intermediate index should be assigned to X. Therefore,
        # backtracking is used here, where BT is set equal to the next
        # month's BT value and X is assigned to the intermediate index
        # associated with that BT value.
        if k > 0:
            if (PX3[k - 1] == 0) and (BT[k - 1] == 0):
                r = 0
                for c in range(k - 1, 0, -1):
                    if BT[c] != 0:
                        # Backtracking continues in a backstepping procedure up through the first month where BT is not equal to zero.
                        r = c + 1    # r is the row number up through which backtracking continues.
                        break

                for count0 in range(k - 1, r - 1, -1):
                    BT[count0] = BT[count0 + 1] # Assign BT to next month's BT value.
                    if BT[count0] == 2:
                        if PX2[count0] == 0: # If BT = 2, X = PX2 unless PX2 = 0, then X = PX1.
                            X[count0] = PX1[count0]
                            BT[count0] = 1
                        else:
                            X[count0] = PX2[count0]
                            BT[count0] = 2
                    elif BT[count0] == 1:
                        if PX1[count0] == 0: # If BT = 1, X = PX1 unless PX1 = 0, then X = PX2.
                            X[count0] = PX2[count0] 
                            BT[count0] = 2
                        else:
                            X[count0] = PX1[count0]
                            BT[count0] = 1

        # In instances where there is no established spell for the last monthly observation, X is initially 
        # assigned to 0. The code below sets X in the last month to greater of |PX1| or |PX2|. This prevents 
        # the PHDI from being inappropriately set to 0. 
        if k == (number_of_months - 1):
            if (PX3[k] == 0) and (X[k] == 0):
                if abs(PX1[k]) > abs(PX2[k]):
                    X[k] = PX1[k]
                else:
                    X[k] = PX2[k]
                
        # round values to four decimal places
        X1 = round(X1, 4)
        X2 = round(X2, 4)
        X3 = round(X3, 4)
        Pe = round(Pe, 4)
        V = round(V, 4)
        PV = round(PV, 4)
        Q = round(Q, 4)
        X[k] = round(X[k], 4)
        PX1[k] = round(PX1[k], 4)
        PX2[k] = round(PX2[k], 4)
        PX3[k] = round(PX3[k], 4)
        PPe[k] = round(PPe[k], 4)
        Ud[k] = round(Ud[k], 4)
        Uw[k] = round(Uw[k], 4)
        Ze[k] = round(Ze[k], 4)
        
    ## ASSIGN PDSI VALUES
    # NOTE: 
    # In Palmer's effort to create a meteorological drought index (PDSI),
    # Palmer expressed the beginning and ending of dry (or wet) periods in
    # terms of the probability that the spell has started or ended (Pe). A
    # drought (wet spell) is definitely over when the probability reaches
    # or exceeds 100%, but the drought (wet spell) is considered to have
    # ended the first month when the probability becomes greater than 0%
    # and then continues to remain greater than 0% until it reaches 100% 
    # (cf. Palmer, 1965; US Weather Bureau Research Paper 45).
    PDSI = X
    
    ## ASSIGN PHDI VALUES
    # NOTE:
    # There is a lag between the time that the drought-inducing
    # meteorological conditions end and the environment recovers from a
    # drought. Palmer made this distinction by computing a meteorological
    # drought index (described above) and a hydrological drought index. The
    # X3 term changes more slowly than the values of the incipient (X1 and
    # X2) terms. The X3 term is the index for the long-term hydrologic
    # moisture condition and is the PHDI.
    for s in range(len(PX3)):
        if PX3[s] == 0:
            # For calculation and program advancement purposes, the PX3 term is sometimes set equal to 0. 
            # In such instances, the PHDI is set equal to X (the PDSI), which accurately reflects the X3 value.
            PHDI[s] = X[s]
        else:
            PHDI[s] = PX3[s]
    
    # return the computed variables
    return PDSI, PHDI, PMDI

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def pdsi_from_climatology(precip_time_series,
                          temp_time_series,
                          awc,
                          latitude,
                          data_start_year,
                          calibration_start_year,
                          calibration_end_year):

    '''
    This function computes the Palmer Drought Severity Index (PDSI), Palmer Hydrological Drought Index (PHDI), 
    and Palmer Z-Index.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param temperature_time_series: time series of monthly temperature values, in degrees Fahrenheit
    :param awc: available water capacity (soil constant), in inches
    :param latitude: latitude, in degrees north 
    :param data_start_year: initial year of the input precipitation and temperature datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: four numpy arrays containing PDSI, PHDI, PMDI, and Z-Index values respectively 
    '''

    # compute PET
    pet_time_series = thornthwaite(temp_time_series, 
                                   latitude, 
                                   int(temp_time_series.shape[0] / 12),
                                   np.NaN)
                     
    return pdsi(precip_time_series,
                pet_time_series.flatten(),
                awc,
                data_start_year,
                calibration_start_year,
                calibration_end_year)

#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def _duration_factors(pdsi_values,
                     zindex_values,
                     calibration_start_year,
                     calibration_end_year,
                     data_start_year,
                     wet_or_dry):
    '''
    This functions calculates m and b, which are used to calculated X(i)
    based on the Z index.  These constants will determine the
    weight that the previous PDSI value and the current Z index
    will have on the current PDSI value.  This is done by finding
    several of the driest periods at this station and assuming that
    those periods represents an extreme drought.  Then a linear
    regression is done to determine the relationship between length
    of a dry (or wet) spell and the accumulated Z index during that
    same period.
    
    It appears that there needs to be a different weight given to
    negative and positive Z values, so the variable 'sign' will
    determine whether the driest or wettest periods are looked at.

    '''
    month_scales = [3, 6, 9, 12, 18, 24, 30, 36, 42, 48]
    
    z_sums = np.zeros((len(month_scales),))
    for i in range(len(month_scales)):

        z_sums[i] = _z_sum(month_scales[i],
                           wet_or_dry, 
                           zindex_values,
                           12, 
                           calibration_start_year, 
                           calibration_end_year, 
                           data_start_year)
    
    slope, intercept = _least_squares(month_scales, z_sums, len(month_scales), wet_or_dry)
    
    # if we're dealing with wet conditions then we want to be using positive numbers, and if dry conditions then
    # we need to be using negative numbers, so we use a PDSI limit of 4 on the wet side and -4 on the dry side 
    pdsi_limit = _PDSI_MAX  # WET
    if 'DRY' == wet_or_dry:

        pdsi_limit = _PDSI_MIN
    
    # now divide slope and intercept by 4 or -4 because that line represents a PDSI of either 4.0 or -4.0
    slope = slope / pdsi_limit
    intercept = intercept / pdsi_limit            

    return slope, intercept

#-----------------------------------------------------------------------------------------------------------------------
#@numba.jit
def _pdsi_at_percentile(pdsi_values,
                        percentile):

    pdsiSorted = sorted(pdsi_values)
    return pdsiSorted[int(len(pdsi_values) * percentile)]
    
#-----------------------------------------------------------------------------------------------------------------------
@numba.jit
def _calibrate(pdsi_values,
               sczindex_values,
               calibration_start_year,
               calibration_end_year,
               input_start_year):
    
    # remove periods before the end of the interval
    # calibrate using upper and lower 2% of values within the user-defined calibration interval
    # this is explained in equations (14) and (15) of Wells et al
    dry_ratio = _PDSI_MIN / _pdsi_at_percentile(pdsi_values, 0.02) 
    wet_ratio = _PDSI_MAX / _pdsi_at_percentile(pdsi_values, 0.98) 
        
    # adjust the self-calibrated Z-index values, using either the wet or dry ratio
    #TODO replace the below loop with a vectorized equivalent
    for time_step in range(sczindex_values.size):
    
        if not np.isnan(sczindex_values[time_step]):
        
            if sczindex_values[time_step] >= 0:
            
                adjustmentFactor = wet_ratio
            
            else:
            
                adjustmentFactor = dry_ratio

            sczindex_values[time_step] = sczindex_values[time_step] * adjustmentFactor

    # allocate arrays which will be populated in the following step
    established_index_values = np.full(pdsi_values.shape, np.NaN)
    scpdsi_values = np.full(pdsi_values.shape, np.NaN)
    wet_index_values = np.full(pdsi_values.shape, np.NaN)
    dry_index_values = np.full(pdsi_values.shape, np.NaN)
    wet_index_deque = deque([])
    dry_index_deque = deque([])
    
    wet_m, wet_b = _duration_factors(pdsi_values,
                                     sczindex_values,
                                     calibration_start_year,
                                     calibration_end_year,
                                     input_start_year,
                                     'WET')
    dry_m, dry_b = _duration_factors(pdsi_values,
                                     sczindex_values,
                                     calibration_start_year,
                                     calibration_end_year,
                                     input_start_year,
                                     'DRY')
    
#     logger.debug('wet_m: {0}   wet_b: {1}   dry_m: {2}   dry_b: {3}'.format(wet_m, wet_b, dry_m, dry_b))
    
    pdsi_values, scpdsi_values, wet_index_values, dry_index_values, established_index_values = \
        _compute_X(established_index_values,
                   sczindex_values,
                   scpdsi_values,
                   pdsi_values,
                   wet_index_values,
                   dry_index_values,
                   wet_index_deque,
                   dry_index_deque,
                   wet_m,
                   wet_b,
                   dry_m,
                   dry_b,
                   False);

    return sczindex_values, pdsi_values, scpdsi_values

#-----------------------------------------------------------------------------------------------------------------------
def scpdsi(precip_time_series,
           pet_time_series,
           awc,
           data_start_year,
           calibration_start_year,
           calibration_end_year):
    '''
    This function computes the Palmer Drought Severity Index (PDSI), Palmer Hydrological Drought Index (PHDI), 
    Modified Palmer Drought Index (PMDI), and Palmer Z-Index.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param pet_time_series: time series of monthly PET values, in inches
    :param awc: available water capacity (soil constant), in inches
    :param data_start_year: initial year of the input precipitation and PET datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: three numpy arrays, respectively containing PDSI, PHDI, and Z-Index values  
    '''
    try:
        # make sure we have matching precipitation and PET time series
        if precip_time_series.size != pet_time_series.size:
            message = 'Precipitation and PET time series do not match, unequal number or months'
            logger.error(message)
            raise ValueError(message)
                    
        # perform water balance accounting
        ET, PR, R, RO, PRO, L, PL = water_balance(awc, pet_time_series, precip_time_series)
        
        # if we have input time series (precipitation and PET) with an incomplete 
        # final year then we pad all the time series arrays with NaN values
        pad_months = 12 - (precip_time_series.size % 12)
        if pad_months > 0:            
            precip_time_series = np.pad(precip_time_series, (0, pad_months), 'constant', constant_values=(np.nan))
            pet_time_series = np.pad(pet_time_series, (0, pad_months), 'constant', constant_values=(np.nan))
            ET = np.pad(ET, (0, pad_months), 'constant', constant_values=(np.nan))
            PR = np.pad(PR, (0, pad_months), 'constant', constant_values=(np.nan))
            R = np.pad(R, (0, pad_months), 'constant', constant_values=(np.nan))
            RO = np.pad(RO, (0, pad_months), 'constant', constant_values=(np.nan))
            PRO = np.pad(PRO, (0, pad_months), 'constant', constant_values=(np.nan))
            L = np.pad(L, (0, pad_months), 'constant', constant_values=(np.nan))
            PL = np.pad(PL, (0, pad_months), 'constant', constant_values=(np.nan))
                
        # compute Z-index values
        zindex = z_index(precip_time_series, 
                         pet_time_series, 
                         ET, 
                         PR, 
                         R, 
                         RO, 
                         PRO, 
                         L, 
                         PL, 
                         data_start_year, 
                         calibration_start_year, 
                         calibration_end_year)
        
        # trim off the padded months from the Z-index array
        if pad_months > 0:
            zindex = zindex[0:-pad_months]
            ET = ET[0:-pad_months]
            PR = PR[0:-pad_months]
            R = R[0:-pad_months]
            RO = RO[0:-pad_months]
            PRO = PRO[0:-pad_months]
            L = L[0:-pad_months]
            PL = PL[0:-pad_months]
            
        # compute PDSI and other associated variables
        PDSI, PHDI, PMDI = pdsi_from_zindex(zindex)

        # keep a copy of the originally computed PDSI for return
        final_PDSI = np.array(PDSI)
        
        # perform self-calibration        
        zindex, PDSI, SCPDSI = _calibrate(PDSI, 
                                          zindex,
                                          calibration_start_year,
                                          calibration_end_year,
                                          data_start_year)

        # recompute PDSI and other associated variables
        SCPDSI, PHDI, PMDI = pdsi_from_zindex(zindex)
        
        #FIXME is this necessary/redundant after the trim above?
        ET = ET[:SCPDSI.size]
        
#         return SCPDSI, final_PDSI, PHDI, PMDI, zindex
        return SCPDSI, final_PDSI, PHDI, PMDI, zindex, ET, PR, R, RO, PRO, L, PL  # include additional water balance values for debugging
    
    except:
        # catch all exceptions, log rudimentary error information
        logger.error('Failed to complete', exc_info=True)
        raise

#-----------------------------------------------------------------------------------------------------------------------
def pdsi(precip_time_series,
         pet_time_series,
         awc,
         data_start_year,
         calibration_start_year=1931,
         calibration_end_year=1990):
    '''
    This function computes the Palmer Drought Severity Index (PDSI), Palmer Hydrological Drought Index (PHDI), 
    and Palmer Z-Index.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param pet_time_series: time series of monthly PET values, in inches
    :param awc: available water capacity (soil constant), in inches
    :param data_start_year: initial year of the input precipitation and PET datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: four numpy arrays containing PDSI, PHDI, PMDI, and Z-Index values respectively 
    '''
    try:
        # make sure we have matching precipitation and PET time series
        if precip_time_series.size != pet_time_series.size:
            message = 'Precipitation and PET time series do not match, unequal number or months'
            logger.error(message)
            raise ValueError(message)
                    
        # perform water balance accounting
        ET, PR, R, RO, PRO, L, PL = water_balance(awc, pet_time_series, precip_time_series)
        
#         # for debugging, print out the water balance variables
#         print('\nWater Balance variables\n')
#         print_values(ET, 'ET')
#         print_values(PR, 'Potential Recharge: ')
#         print_values(R, 'Recharge: ')
#         print_values(RO, 'Runoff')
#         print_values(PRO, 'Potential Runoff: ')
#         print_values(L, 'Loss')
#         print_values(PL, 'Potential Loss: ')
        
        # if we have input time series (precipitation and PET) with an incomplete 
        # final year then we pad all the time series arrays with NaN values
        pad_months = 12 - (precip_time_series.size % 12)
        if pad_months > 0:            
            precip_time_series = np.pad(precip_time_series, (0, pad_months), 'constant', constant_values=(np.nan))
            pet_time_series = np.pad(pet_time_series, (0, pad_months), 'constant', constant_values=(np.nan))
            ET = np.pad(ET, (0, pad_months), 'constant', constant_values=(np.nan))
            PR = np.pad(PR, (0, pad_months), 'constant', constant_values=(np.nan))
            R = np.pad(R, (0, pad_months), 'constant', constant_values=(np.nan))
            RO = np.pad(RO, (0, pad_months), 'constant', constant_values=(np.nan))
            PRO = np.pad(PRO, (0, pad_months), 'constant', constant_values=(np.nan))
            L = np.pad(L, (0, pad_months), 'constant', constant_values=(np.nan))
            PL = np.pad(PL, (0, pad_months), 'constant', constant_values=(np.nan))
                
        # compute Z-index values
        zindex = z_index(precip_time_series, 
                         pet_time_series, 
                         ET, 
                         PR, 
                         R, 
                         RO, 
                         PRO, 
                         L, 
                         PL, 
                         data_start_year, 
                         calibration_start_year, 
                         calibration_end_year)
        
        # trim off the padded months from the Z-index array
        if pad_months > 0:
            zindex = zindex[0:-pad_months]
            
        # compute PDSI and other associated variables
        PDSI, PHDI, PMDI = pdsi_from_zindex(zindex)
        
        return PDSI, PHDI, PMDI, zindex
    
    except:
        # catch all exceptions, log rudimentary error information
        logger.error('Failed to complete', exc_info=True)
        raise
