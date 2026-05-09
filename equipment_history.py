"""
Equipment History Module
Provides comprehensive equipment history tracking and timeline visualization including:
- Complete PM history
- Corrective maintenance history
- Parts usage history
- Timeline visualization
- Equipment health scoring
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict


class EquipmentHistory:
    """Manages equipment history data and analysis"""

    def __init__(self, conn):
        """
        Initialize equipment history manager

        Args:
            conn: Database connection
        """
        self.conn = conn

    def get_complete_history(self, bfm_no: str, start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Dict[str, List[Dict]]:
        """
        Get complete history for equipment including PMs, CMs, and parts

        Args:
            bfm_no: BFM equipment number
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)

        Returns:
            Dictionary with categorized history records
        """
        try:
            history = {
                'pm_completions': [],
                'corrective_maintenance': [],
                'parts_used': [],
                'status_changes': []
            }

            # Get PM completions
            history['pm_completions'] = self._get_pm_history(bfm_no, start_date, end_date)

            # Get corrective maintenance
            history['corrective_maintenance'] = self._get_cm_history(bfm_no, start_date, end_date)

            # Get parts usage
            history['parts_used'] = self._get_parts_history(bfm_no, start_date, end_date)

            # Get status changes from audit log
            history['status_changes'] = self._get_status_changes(bfm_no, start_date, end_date)

            # Commit to end transaction cleanly
            self.conn.commit()

            return history
        except Exception as e:
            # Rollback on error
            try:
                self.conn.rollback()
            except:
                pass
            raise e

    def _get_pm_history(self, bfm_no: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict]:
        """Get PM completion history"""
        cursor = self.conn.cursor()

        query = '''
            SELECT completion_date, pm_type, technician_name, labor_hours,
                   notes, special_equipment
            FROM pm_completions
            WHERE bfm_equipment_no = %s
        '''
        params = [bfm_no]

        if start_date:
            query += ' AND completion_date >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND completion_date <= %s'
            params.append(end_date)

        query += ' ORDER BY completion_date DESC'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'date': row[0],
                'type': 'PM',
                'pm_type': row[1],
                'technician': row[2],
                'labor_hours': row[3],
                'notes': row[4],
                'special_equipment': row[5]
            })

        return results

    def _get_cm_history(self, bfm_no: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict]:
        """Get corrective maintenance history"""
        cursor = self.conn.cursor()

        query = '''
            SELECT cm_number, reported_date, closed_date, description, priority,
                   status, assigned_technician, labor_hours, notes, notes
            FROM corrective_maintenance
            WHERE bfm_equipment_no = %s
        '''
        params = [bfm_no]

        if start_date:
            query += ' AND reported_date >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND reported_date <= %s'
            params.append(end_date)

        query += ' ORDER BY reported_date DESC'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'type': 'CM',
                'cm_number': row[0],
                'date_opened': row[1],
                'date_closed': row[2],
                'description': row[3],
                'priority': row[4],
                'status': row[5],
                'assigned_to': row[6],
                'labor_hours': row[7],
                'root_cause': row[8],
                'corrective_action': row[9]
            })

        return results

    def _get_parts_history(self, bfm_no: str, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> List[Dict]:
        """Get parts usage history"""
        cursor = self.conn.cursor()

        # Get parts from CM parts requests
        query = '''
            SELECT cpr.requested_date, cpr.part_number, cpr.model_number,
                   cpr.requested_by, cpr.notes, cm.cm_number
            FROM cm_parts_requests cpr
            JOIN corrective_maintenance cm ON cpr.cm_number = cm.cm_number
            WHERE cm.bfm_equipment_no = %s
        '''
        params = [bfm_no]

        if start_date:
            query += ' AND cpr.requested_date >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND cpr.requested_date <= %s'
            params.append(end_date)

        query += ' ORDER BY cpr.requested_date DESC'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'type': 'PART',
                'date': row[0],
                'part_number': row[1],
                'model_number': row[2],
                'requested_by': row[3],
                'notes': row[4],
                'cm_number': row[5]
            })

        return results

    def _get_status_changes(self, bfm_no: str, start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> List[Dict]:
        """Get status changes from audit log"""
        cursor = self.conn.cursor()

        query = '''
            SELECT timestamp, action, user_id, old_values, new_values
            FROM audit_log
            WHERE table_name = 'equipment'
            AND record_id = %s
        '''
        params = [bfm_no]

        if start_date:
            query += ' AND timestamp >= %s'
            params.append(start_date)
        if end_date:
            query += ' AND timestamp <= %s'
            params.append(end_date)

        query += ' ORDER BY timestamp DESC'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'type': 'STATUS_CHANGE',
                'date': row[0],
                'action': row[1],
                'user': row[2],
                'old_values': row[3],
                'new_values': row[4]
            })

        return results

    def get_timeline_events(self, bfm_no: str, days: int = 365) -> List[Dict]:
        """
        Get timeline events for visualization

        Args:
            bfm_no: BFM equipment number
            days: Number of days to look back

        Returns:
            List of events sorted by date
        """
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        history = self.get_complete_history(bfm_no, start_date=start_date)

        # Combine all events into a single timeline
        events = []

        # Add PM completions
        for pm in history['pm_completions']:
            events.append({
                'date': pm['date'],
                'type': 'PM',
                'category': 'Preventive Maintenance',
                'title': f"{pm['pm_type']} PM",
                'details': f"Technician: {pm['technician']}, Hours: {pm['labor_hours']}",
                'notes': pm['notes'],
                'color': '#4CAF50'  # Green
            })

        # Add CM records
        for cm in history['corrective_maintenance']:
            events.append({
                'date': cm['date_opened'],
                'type': 'CM_OPEN',
                'category': 'Corrective Maintenance',
                'title': f"CM {cm['cm_number']} Opened",
                'details': f"Priority: {cm['priority']}, Assigned: {cm['assigned_to']}",
                'notes': cm['description'],
                'color': '#FF9800'  # Orange
            })

            if cm['date_closed']:
                events.append({
                    'date': cm['date_closed'],
                    'type': 'CM_CLOSE',
                    'category': 'Corrective Maintenance',
                    'title': f"CM {cm['cm_number']} Closed",
                    'details': f"Hours: {cm['labor_hours']}",
                    'notes': cm['corrective_action'],
                    'color': '#4CAF50'  # Green
                })

        # Add parts usage
        for part in history['parts_used']:
            events.append({
                'date': part['date'],
                'type': 'PART',
                'category': 'Parts Request',
                'title': f"Part: {part['part_number']}",
                'details': f"Model: {part['model_number']}, Requested by: {part['requested_by']}",
                'notes': f"CM: {part['cm_number']}, Notes: {part['notes']}",
                'color': '#2196F3'  # Blue
            })

        # Add status changes
        for change in history['status_changes']:
            events.append({
                'date': change['date'],
                'type': 'STATUS',
                'category': 'Status Change',
                'title': f"Status Changed",
                'details': f"By: {change['user']}",
                'notes': f"From: {change['old_values']} To: {change['new_values']}",
                'color': '#9C27B0'  # Purple
            })

        # Sort by date (most recent first)
        events.sort(key=lambda x: x['date'], reverse=True)

        return events

    def get_equipment_health_score(self, bfm_no: str) -> Dict:
        """
        Calculate equipment health score based on maintenance history

        Args:
            bfm_no: BFM equipment number

        Returns:
            Dictionary with health metrics
        """
        try:
            cursor = self.conn.cursor()

            metrics = {
                'health_score': 0,  # 0-100
                'pm_compliance': 0,  # Percentage of on-time PMs
                'cm_frequency': 0,  # CMs per month
                'downtime_days': 0,  # Average downtime
                'parts_cost': 0,  # Total parts cost (last 12 months)
                'labor_hours': 0,  # Total labor hours (last 12 months)
                'status': 'Unknown',
                'recommendations': []
            }

            # Get equipment info
            cursor.execute('SELECT status, monthly_pm, annual_pm FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            equip_row = cursor.fetchone()
            if not equip_row:
                return metrics

            metrics['status'] = equip_row[0]

            # Calculate PM compliance (last 12 months)
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            # Count expected PMs
            expected_pms = 0
            if equip_row[1]:  # Has monthly PM (boolean)
                expected_pms += 12
            if equip_row[2]:  # Has annual PM (boolean)
                expected_pms += 1

            # Count completed PMs
            cursor.execute('''
                SELECT COUNT(*)
                FROM pm_completions
                WHERE bfm_equipment_no = %s
                AND completion_date >= %s
            ''', (bfm_no, one_year_ago))
            completed_pms = cursor.fetchone()[0]

            if expected_pms > 0:
                metrics['pm_compliance'] = min(100, int((completed_pms / expected_pms) * 100))

            # Count CMs in last 12 months
            cursor.execute('''
                SELECT COUNT(*)
                FROM corrective_maintenance
                WHERE bfm_equipment_no = %s
                AND reported_date >= %s
            ''', (bfm_no, one_year_ago))
            cm_count = cursor.fetchone()[0]
            metrics['cm_frequency'] = round(cm_count / 12, 1)

            # Calculate total labor hours
            cursor.execute('''
                SELECT COALESCE(SUM(labor_hours), 0)
                FROM pm_completions
                WHERE bfm_equipment_no = %s
                AND completion_date >= %s
            ''', (bfm_no, one_year_ago))
            pm_hours = cursor.fetchone()[0] or 0

            cursor.execute('''
                SELECT COALESCE(SUM(labor_hours), 0)
                FROM corrective_maintenance
                WHERE bfm_equipment_no = %s
                AND reported_date >= %s
            ''', (bfm_no, one_year_ago))
            cm_hours = cursor.fetchone()[0] or 0

            metrics['labor_hours'] = float(pm_hours) + float(cm_hours)

            # Calculate parts count (cost data not available in schema)
            cursor.execute('''
                SELECT COUNT(*)
                FROM cm_parts_requests cpr
                JOIN corrective_maintenance cm ON cpr.cm_number = cm.cm_number
                WHERE cm.bfm_equipment_no = %s
                AND cpr.requested_date >= %s
            ''', (bfm_no, one_year_ago))
            metrics['parts_cost'] = 0  # Not available in current schema
            metrics['parts_count'] = cursor.fetchone()[0] or 0

            # Calculate health score (0-100)
            score = 100

            # Deduct for poor PM compliance
            score -= (100 - metrics['pm_compliance']) * 0.3

            # Deduct for high CM frequency (more than 1 per month is concerning)
            if metrics['cm_frequency'] > 1:
                score -= min(20, (metrics['cm_frequency'] - 1) * 10)

            # Deduct for inactive status
            if metrics['status'] != 'Active':
                score -= 30

            metrics['health_score'] = max(0, int(score))

            # Generate recommendations
            if metrics['pm_compliance'] < 80:
                metrics['recommendations'].append("Improve PM compliance - currently below 80%")
            if metrics['cm_frequency'] > 2:
                metrics['recommendations'].append("High CM frequency - investigate root causes")
            if metrics['parts_count'] > 20:
                metrics['recommendations'].append("High parts usage - review equipment reliability")
            if metrics['status'] != 'Active':
                metrics['recommendations'].append(f"Equipment status is '{metrics['status']}' - review and update")

            # Commit to end transaction cleanly
            self.conn.commit()

            return metrics
        except Exception as e:
            # Rollback on error
            try:
                self.conn.rollback()
            except:
                pass
            raise e

    def get_maintenance_trends(self, bfm_no: str, months: int = 12) -> Dict:
        """
        Get maintenance trends over time

        Args:
            bfm_no: BFM equipment number
            months: Number of months to analyze

        Returns:
            Dictionary with trend data
        """
        try:
            cursor = self.conn.cursor()

            trends = {
                'monthly_pm_counts': [],
                'monthly_cm_counts': [],
                'monthly_labor_hours': [],
                'monthly_parts_cost': [],
                'months': []
            }

            # Generate month labels
            current_date = datetime.now()
            for i in range(months):
                month_date = current_date - timedelta(days=30 * i)
                trends['months'].insert(0, month_date.strftime('%Y-%m'))

            # Get monthly data
            for month in trends['months']:
                month_start = f"{month}-01"
                # Calculate month end
                year, mon = map(int, month.split('-'))
                if mon == 12:
                    month_end = f"{year + 1}-01-01"
                else:
                    month_end = f"{year}-{mon + 1:02d}-01"

                # PM count
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM pm_completions
                    WHERE bfm_equipment_no = %s
                    AND completion_date >= %s
                    AND completion_date < %s
                ''', (bfm_no, month_start, month_end))
                trends['monthly_pm_counts'].append(cursor.fetchone()[0])

                # CM count
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM corrective_maintenance
                    WHERE bfm_equipment_no = %s
                    AND reported_date >= %s
                    AND reported_date < %s
                ''', (bfm_no, month_start, month_end))
                trends['monthly_cm_counts'].append(cursor.fetchone()[0])

                # Labor hours
                cursor.execute('''
                    SELECT COALESCE(SUM(labor_hours), 0)
                    FROM pm_completions
                    WHERE bfm_equipment_no = %s
                    AND completion_date >= %s
                    AND completion_date < %s
                ''', (bfm_no, month_start, month_end))
                pm_hours = cursor.fetchone()[0] or 0

                cursor.execute('''
                    SELECT COALESCE(SUM(labor_hours), 0)
                    FROM corrective_maintenance
                    WHERE bfm_equipment_no = %s
                    AND reported_date >= %s
                    AND reported_date < %s
                ''', (bfm_no, month_start, month_end))
                cm_hours = cursor.fetchone()[0] or 0

                trends['monthly_labor_hours'].append(float(pm_hours) + float(cm_hours))

            # Commit to end transaction cleanly
            self.conn.commit()

            return trends
        except Exception as e:
            # Rollback on error
            try:
                self.conn.rollback()
            except:
                pass
            raise e


class EquipmentHistoryViewer:
    """GUI for viewing equipment history timeline"""

    def __init__(self, parent, conn, bfm_no: str):
        """
        Initialize history viewer window

        Args:
            parent: Parent tkinter window
            conn: Database connection
            bfm_no: BFM equipment number
        """
        self.conn = conn
        self.bfm_no = bfm_no
        self.history_manager = EquipmentHistory(conn)

        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title(f"Equipment History - {bfm_no}")
        self.window.geometry("1200x800")

        # Make window modal
        self.window.transient(parent)
        self.window.grab_set()

        self._create_ui()
        self._load_history()

    def _create_ui(self):
        """Create user interface"""
        # Header
        header_frame = ttk.Frame(self.window)
        header_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(header_frame, text=f"Equipment History: {self.bfm_no}",
                 font=('Arial', 14, 'bold')).pack(side='left')

        # Filter frame
        filter_frame = ttk.LabelFrame(self.window, text="Filters")
        filter_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(filter_frame, text="Show last:").pack(side='left', padx=5)

        self.days_var = tk.StringVar(value="365")
        days_combo = ttk.Combobox(filter_frame, textvariable=self.days_var,
                                  values=["30", "90", "180", "365", "730"],
                                  width=10, state='readonly')
        days_combo.pack(side='left', padx=5)
        days_combo.bind('<<ComboboxSelected>>', lambda e: self._load_history())

        ttk.Label(filter_frame, text="days").pack(side='left')

        ttk.Button(filter_frame, text="Refresh",
                  command=self._load_history).pack(side='right', padx=5)

        # Notebook for different views
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill='both', expand=True, padx=10, pady=5)

        # Timeline tab
        timeline_frame = ttk.Frame(notebook)
        notebook.add(timeline_frame, text="Timeline")
        self._create_timeline_view(timeline_frame)

        # Health Score tab
        health_frame = ttk.Frame(notebook)
        notebook.add(health_frame, text="Health Score")
        self._create_health_view(health_frame)

        # Summary tab
        summary_frame = ttk.Frame(notebook)
        notebook.add(summary_frame, text="Summary")
        self._create_summary_view(summary_frame)

    def _create_timeline_view(self, parent):
        """Create timeline view"""
        # Scrolled text widget for timeline
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill='both', expand=True)

        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side='right', fill='y')

        self.timeline_tree = ttk.Treeview(scroll_frame, columns=('Date', 'Category', 'Event', 'Details'),
                                          show='tree headings', yscrollcommand=scrollbar.set)
        self.timeline_tree.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.timeline_tree.yview)

        # Configure columns
        self.timeline_tree.heading('#0', text='')
        self.timeline_tree.heading('Date', text='Date')
        self.timeline_tree.heading('Category', text='Category')
        self.timeline_tree.heading('Event', text='Event')
        self.timeline_tree.heading('Details', text='Details')

        self.timeline_tree.column('#0', width=30)
        self.timeline_tree.column('Date', width=100)
        self.timeline_tree.column('Category', width=150)
        self.timeline_tree.column('Event', width=250)
        self.timeline_tree.column('Details', width=400)

    def _create_health_view(self, parent):
        """Create health score view"""
        self.health_text = tk.Text(parent, wrap='word', height=20, width=80)
        self.health_text.pack(fill='both', expand=True, padx=10, pady=10)

    def _create_summary_view(self, parent):
        """Create summary statistics view"""
        self.summary_text = tk.Text(parent, wrap='word', height=20, width=80)
        self.summary_text.pack(fill='both', expand=True, padx=10, pady=10)

    def _load_history(self):
        """Load and display equipment history"""
        try:
            days = int(self.days_var.get())

            # Load timeline events
            events = self.history_manager.get_timeline_events(self.bfm_no, days)

            # Clear timeline
            for item in self.timeline_tree.get_children():
                self.timeline_tree.delete(item)

            # Populate timeline
            for event in events:
                self.timeline_tree.insert('', 'end', values=(
                    event['date'],
                    event['category'],
                    event['title'],
                    event['details']
                ))

            # Load health score
            health = self.history_manager.get_equipment_health_score(self.bfm_no)
            self._display_health_score(health)

            # Load summary
            self._load_summary()

        except Exception as e:
            messagebox.showerror("Error", f"Error loading history: {str(e)}")

    def _display_health_score(self, health: Dict):
        """Display health score information"""
        self.health_text.delete('1.0', 'end')

        score = health['health_score']
        color = 'green' if score >= 80 else 'orange' if score >= 60 else 'red'

        text = f"""
EQUIPMENT HEALTH SCORE: {score}/100

Status: {health['status']}

METRICS:
- PM Compliance: {health['pm_compliance']}%
- CM Frequency: {health['cm_frequency']} per month
- Total Labor Hours (12 months): {health['labor_hours']:.1f} hours
- Parts Requests (12 months): {health.get('parts_count', 0)} requests

RECOMMENDATIONS:
"""
        for rec in health['recommendations']:
            text += f"- {rec}\n"

        if not health['recommendations']:
            text += "- No issues detected. Equipment is performing well.\n"

        self.health_text.insert('1.0', text)

    def _load_summary(self):
        """Load and display summary statistics"""
        self.summary_text.delete('1.0', 'end')

        days = int(self.days_var.get())
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        history = self.history_manager.get_complete_history(self.bfm_no, start_date=start_date)

        pm_count = len(history['pm_completions'])
        cm_count = len(history['corrective_maintenance'])
        parts_count = len(history['parts_used'])

        # Calculate totals
        total_pm_hours = sum(float(pm.get('labor_hours', 0) or 0) for pm in history['pm_completions'])
        total_cm_hours = sum(float(cm.get('labor_hours', 0) or 0) for cm in history['corrective_maintenance'])

        text = f"""
SUMMARY (Last {days} days)

PREVENTIVE MAINTENANCE:
- Total PMs: {pm_count}
- Total PM Hours: {total_pm_hours:.1f}
- Monthly PMs: {len([p for p in history['pm_completions'] if p['pm_type'] == 'Monthly'])}
- Annual PMs: {len([p for p in history['pm_completions'] if p['pm_type'] == 'Annual'])}

CORRECTIVE MAINTENANCE:
- Total CMs: {cm_count}
- Total CM Hours: {total_cm_hours:.1f}
- Open CMs: {len([c for c in history['corrective_maintenance'] if c['status'] != 'Closed'])}
- Closed CMs: {len([c for c in history['corrective_maintenance'] if c['status'] == 'Closed'])}

PARTS:
- Parts Requests: {parts_count}

TOTAL MAINTENANCE HOURS: {total_pm_hours + total_cm_hours:.1f}
"""

        self.summary_text.insert('1.0', text)


def show_equipment_history(parent, conn, bfm_no: str):
    """
    Show equipment history viewer window

    Args:
        parent: Parent tkinter window
        conn: Database connection
        bfm_no: BFM equipment number
    """
    EquipmentHistoryViewer(parent, conn, bfm_no)
