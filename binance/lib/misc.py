import math
import datetime
import fractions
import decimal

def truncate(f, n):
    if f >= 1.0:
        return int(f)
    else:
        return math.floor((f * 10 ** n)) / 10 ** n

def truncate_float(f, n):
    '''Truncates/pads a float f to n decimal places without rounding'''
    s = '{}'.format(f)
    if 'e' in s or 'E' in s:
        return float('{0:.{1}f}'.format(f, n))
    else:
        i, p, d = s.partition('.')
        return float('.'.join([i, (d+'0'*n)[:n]]))

def ceiling_float(f, n):
    return math.ceil(f*(10**n))/(10**n)

def float_eq(a, b, n):
    tol = ["0.1", "0.01", "0.001", "0.0001", "0.00001"][n-1]
    pat = ["{:.1f}", "{:.2f}", "{:.3f}", "{:.4f}", "{:.5f}"][n-1]

    f_a = fractions.Fraction(pat.format(a))
    f_b = fractions.Fraction(pat.format(b))
    f_tol = fractions.Fraction(tol)
    return abs(f_a - f_b)<=f_tol

def float_lt(a, b, n):
    tol = ["0.1", "0.01", "0.001", "0.0001", "0.00001"][n-1]
    pat = ["{:.1f}", "{:.2f}", "{:.3f}", "{:.4f}", "{:.5f}"][n-1]

    f_a = fractions.Fraction(pat.format(a))
    f_b = fractions.Fraction(pat.format(b))
    f_tol = fractions.Fraction(tol)
    return f_a - f_b < (0-f_tol)

def float_gt(a, b, n):
    tol = ["0.1", "0.01", "0.001", "0.0001", "0.00001"][n-1]
    pat = ["{:.1f}", "{:.2f}", "{:.3f}", "{:.4f}", "{:.5f}"][n-1]

    f_a = fractions.Fraction(pat.format(a))
    f_b = fractions.Fraction(pat.format(b))
    f_tol = fractions.Fraction(tol)
    return f_a - f_b > f_tol


def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def now():
    return datetime.datetime.now()

def get_relative_ratio(v1, v2):
    if v1 > v2 and v2 != 0:
        return v1/v2
    else:
        return v2/v1

def get_time_str(time_stamp):
    d = datetime.datetime.fromtimestamp(time_stamp/1000 + 12*3600)
    return d.strftime("%Y-%m-%d %H:%M:%S")

def datetime_to_str(d):
    return d.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    f_a = fractions.Fraction('0.0062')
    f_b = fractions.Fraction('0.083333117')
    print (float(f_a*11))
    print (float(f_a + f_b))
    f_a = fractions.Fraction(1,7)
    print (f_a)
    print (float(f_a))


    print (fractions.Fraction(1000))
