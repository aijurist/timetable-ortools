# Unicode Encoding Error Fix

## Issue Identified
The timetable scheduler was encountering a `UnicodeEncodeError` when saving constraint summaries:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 84: character maps to <undefined>
```

## Root Cause Analysis

### 1. **Unicode Characters in Constraint Examples**
The Monday/Saturday constraint example contained Unicode arrow characters (→ which is \u2192):
```python
"example": "Teacher A: Works Monday (theory + lab) → Cannot work Saturday"
```

### 2. **Default Windows Encoding**
Windows uses the 'charmap' codec (cp1252) by default, which cannot handle Unicode characters like →, causing the encoding error when writing files.

### 3. **Missing UTF-8 Encoding Specification**
File writing operations were not explicitly specifying UTF-8 encoding:
```python
# Problematic code
with open(file_path, 'w') as f:  # Uses default system encoding
    f.write(content_with_unicode)
```

## Solution Implemented

### 1. **Replaced Unicode Characters with ASCII Alternatives**

**Before:**
```python
"example": "Teacher A: Works Monday (theory + lab) → Cannot work Saturday"
```

**After:**
```python
"example": "Teacher A: Works Monday (theory + lab) -> Cannot work Saturday"
```

### 2. **Added UTF-8 Encoding to All File Operations**

#### Constraint Summary Files (`scheduler.py`)
```python
# JSON file with UTF-8 encoding
with open(constraint_summary_path, 'w', encoding='utf-8') as f:
    json.dump(constraint_summary, f, indent=4, ensure_ascii=False)

# Text file with UTF-8 encoding  
with open(constraint_summary_txt_path, 'w', encoding='utf-8') as f:
    f.write("Timetable Scheduling Constraints Summary\n")
```

#### CSV Files (`scheduler.py`)
```python
# Schedule CSV with UTF-8 encoding
schedule_df.to_csv(schedule_csv_path, index=False, encoding='utf-8')

# Teacher schedules with UTF-8 encoding
teacher_schedule.to_csv(teacher_schedule_path, index=False, encoding='utf-8')

# Room schedules with UTF-8 encoding
room_schedule.to_csv(room_schedule_path, index=False, encoding='utf-8')
```

#### Summary Text File (`scheduler.py`)
```python
# Summary file with UTF-8 encoding
with open(summary_path, 'w', encoding='utf-8') as f:
    f.write("Timetable Schedule Summary\n")
```

## Technical Details

### Character Replacement
- **Unicode arrows (→)** replaced with **ASCII arrows (->)**
- Maintains readability while ensuring compatibility
- No loss of semantic meaning

### Encoding Strategy
- **UTF-8 encoding**: Universal support for all Unicode characters
- **ensure_ascii=False**: Allows JSON to store Unicode characters properly
- **Explicit encoding specification**: Prevents system default encoding issues

## Files Modified

1. **`src/constraints.py`**:
   - Replaced Unicode arrows in Monday/Saturday constraint example

2. **`src/scheduler.py`**:
   - Added UTF-8 encoding to `save_constraint_summary()` method
   - Added UTF-8 encoding to all CSV writing operations
   - Added UTF-8 encoding to `generate_summary()` method

## Benefits

### 1. **Cross-Platform Compatibility**
- Works on Windows (cp1252), Linux (UTF-8), and macOS (UTF-8)
- No more encoding-related crashes

### 2. **Unicode Support**
- Can handle teacher names with accents (José, François, etc.)
- Supports international characters in course names
- Future-proof for multilingual content

### 3. **Data Integrity**
- Preserves all character information correctly
- No garbled text in output files
- Consistent encoding across all file formats

## Verification

✅ **All components tested and verified**:
- ✅ Constraint example uses ASCII arrows
- ✅ UTF-8 file writing works correctly
- ✅ UTF-8 JSON writing works correctly
- ✅ Constraints module imports without errors
- ✅ No Unicode encoding errors during execution

## Error Resolution

### Before Fix:
```
Error in timetable generation: 'charmap' codec can't encode character '\u2192' in position 84: character maps to <undefined>
```

### After Fix:
```
✅ Constraint summaries saved successfully
✅ All output files generated without encoding errors
✅ Unicode characters handled correctly
```

## Future Considerations

### Best Practices Established:
1. **Always specify UTF-8 encoding** for file operations
2. **Use ASCII alternatives** for decorative Unicode characters
3. **Test with international characters** to ensure compatibility
4. **Include encoding parameter** in pandas CSV operations

### Potential Enhancements:
1. **Configuration option** for encoding preference
2. **Automatic encoding detection** for input files
3. **Validation checks** for Unicode content before file writing

The Unicode encoding fix ensures the timetable scheduler works reliably across all platforms and can handle international character sets without errors! 🎉 