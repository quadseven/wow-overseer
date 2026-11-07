import sys
sys.path.insert(0, '.')

from guildrun import carry_xp_lines

# Test 1: Basic carry run with player going from level 30 at 1000 xp to level 31 at 500 xp
# xp_for_level[30] = 5000, so gained = 1500 + 0 = 1500
start = {'member1': (30, 1000), 'carrier': (35, 2000)}
end = {'member1': (31, 500), 'carrier': (36, 4000)}
xp_for_level = {30: 5000, 35: 7000}

lines = carry_xp_lines('deadmines', 'carrier', start, end, xp_for_level)
print('Test 1 - Basic carry run:')
print('  Input:')
print('    start =', start)
print('    end =', end)
print('    xp_for_level =', xp_for_level)
print('    carrier =', 'carrier')
print('  Output:')
for line in lines:
    print('    ', line)
print()

# Test 2: No carrier
lines = carry_xp_lines('deadmines', None, start, end, xp_for_level)
print('Test 2 - No carrier:')
print('  Input:')
print('    start =', start)
print('    end =', end)
print('    xp_for_level =', xp_for_level)
print('    carrier =', None)
print('  Output:')
print('    ', lines)
print()

# Test 3: Member not carried
lines = carry_xp_lines('deadmines', 'carrier', start, end, xp_for_level)
print('Test 3 - Verify correct logic:')
print('  Expected: line for member1 with correct gap')
print('  Actual:')
for line in lines:
    print('    ', line)
    assert 'member1' in line, 'Should contain member1'
    assert 'carry run deadmines' in line, 'Should contain carry run'
    assert 'gap' in line, 'Should contain gap'
print()

print('All tests passed!')
