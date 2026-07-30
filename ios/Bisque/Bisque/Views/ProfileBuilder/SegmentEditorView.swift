import SwiftUI

struct SegmentEditorView: View {
    @Binding var segment: FiringSegment

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Segment Name", text: $segment.name)
                .font(.subheadline.bold())

            HStack(spacing: 16) {
                VStack(alignment: .leading) {
                    Text("Rate (°C/hr)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextField("Rate", value: $segment.rampRate, format: .number)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.numbersAndPunctuation)
                }

                VStack(alignment: .leading) {
                    Text("Target (°C)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextField("Target", value: $segment.targetTemp, format: .number)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.decimalPad)
                }

                VStack(alignment: .leading) {
                    Text("Hold (min)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextField("Hold", value: $segment.holdTime, format: .number)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.decimalPad)
                }
            }

            /* Shown as the value is typed rather than only on Save. The rate
               field is the one that used to crash the app once the profile was
               charted (#143), so naming the problem where it is entered beats
               rejecting it two screens later. */
            if let problem = segment.validationError {
                Text(problem)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(.vertical, 4)
    }
}
