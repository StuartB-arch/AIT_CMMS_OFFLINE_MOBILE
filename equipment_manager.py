"""
Equipment Manager Module
Handles equipment-related operations including:
- Equipment CRUD operations
- Equipment status management
- Equipment search and filtering
- Equipment validation
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime


class EquipmentManager:
    """Manages equipment operations in the CMMS system"""

    def __init__(self, conn):
        """
        Initialize equipment manager

        Args:
            conn: Database connection
        """
        self.conn = conn

    def get_equipment_by_bfm(self, bfm_no: str) -> Optional[Dict]:
        """
        Get equipment details by BFM number

        Args:
            bfm_no: BFM equipment number

        Returns:
            Dictionary with equipment details or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, description, location, monthly_pm, annual_pm,
                   last_monthly_pm, last_annual_pm, next_annual_pm, status
            FROM equipment
            WHERE bfm_equipment_no = %s
        ''', (bfm_no,))

        row = cursor.fetchone()
        if row:
            return {
                'bfm_no': row[0],
                'description': row[1],
                'location': row[2],
                'has_monthly': row[3] if row[3] is not None else False,
                'has_annual': row[4] if row[4] is not None else False,
                'last_monthly_pm': row[5],
                'last_annual_pm': row[6],
                'next_annual_pm': row[7],
                'status': row[8]
            }
        return None

    def search_equipment(self, search_term: str, status_filter: Optional[str] = None) -> List[Dict]:
        """
        Search equipment by BFM number or description

        Args:
            search_term: Search term to match against BFM or description
            status_filter: Optional status filter ('Active', 'Run to Failure', 'Missing')

        Returns:
            List of matching equipment records
        """
        cursor = self.conn.cursor()

        query = '''
            SELECT bfm_equipment_no, description, location, status
            FROM equipment
            WHERE (bfm_equipment_no ILIKE %s OR description ILIKE %s)
        '''
        params = [f'%{search_term}%', f'%{search_term}%']

        if status_filter:
            query += ' AND status = %s'
            params.append(status_filter)

        query += ' ORDER BY bfm_equipment_no LIMIT 100'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'bfm_no': row[0],
                'description': row[1],
                'location': row[2],
                'status': row[3]
            })

        return results

    def get_all_equipment(self, status_filter: Optional[str] = None) -> List[Dict]:
        """
        Get all equipment records

        Args:
            status_filter: Optional status filter

        Returns:
            List of all equipment records
        """
        cursor = self.conn.cursor()

        query = '''
            SELECT bfm_equipment_no, description, location, monthly_pm, annual_pm,
                   last_monthly_pm, last_annual_pm, status
            FROM equipment
        '''
        params = []

        if status_filter:
            query += ' WHERE status = %s'
            params.append(status_filter)

        query += ' ORDER BY bfm_equipment_no'

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'bfm_no': row[0],
                'description': row[1],
                'location': row[2],
                'has_monthly': row[3] if row[3] is not None else False,
                'has_annual': row[4] if row[4] is not None else False,
                'last_monthly_pm': row[5],
                'last_annual_pm': row[6],
                'status': row[7]
            })

        return results

    def update_equipment_status(self, bfm_no: str, new_status: str, user_id: str) -> bool:
        """
        Update equipment status

        Args:
            bfm_no: BFM equipment number
            new_status: New status value
            user_id: User making the change

        Returns:
            True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()

            # Get old status for audit
            cursor.execute('SELECT status FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            old_row = cursor.fetchone()
            old_status = old_row[0] if old_row else None

            # Update status
            cursor.execute('''
                UPDATE equipment
                SET status = %s
                WHERE bfm_equipment_no = %s
            ''', (new_status, bfm_no))

            # Log audit trail
            cursor.execute('''
                INSERT INTO audit_log (table_name, record_id, action, user_id, old_values, new_values, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                'equipment',
                bfm_no,
                'update',
                user_id,
                f'{{"status": "{old_status}"}}',
                f'{{"status": "{new_status}"}}',
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))

            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating equipment status: {e}")
            self.conn.rollback()
            return False

    def update_equipment_pm_dates(self, bfm_no: str, pm_type: str, completion_date: str, user_id: str) -> bool:
        """
        Update equipment PM completion dates

        Args:
            bfm_no: BFM equipment number
            pm_type: PM type ('Monthly' or 'Annual')
            completion_date: Completion date string
            user_id: User making the change

        Returns:
            True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()

            if pm_type == 'Monthly':
                cursor.execute('''
                    UPDATE equipment
                    SET last_monthly_pm = %s
                    WHERE bfm_equipment_no = %s
                ''', (completion_date, bfm_no))
            elif pm_type == 'Annual':
                cursor.execute('''
                    UPDATE equipment
                    SET last_annual_pm = %s
                    WHERE bfm_equipment_no = %s
                ''', (completion_date, bfm_no))

            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating PM dates: {e}")
            self.conn.rollback()
            return False

    def get_equipment_statistics(self) -> Dict:
        """
        Get equipment statistics

        Returns:
            Dictionary with various equipment statistics
        """
        cursor = self.conn.cursor()

        stats = {}

        # Total equipment
        cursor.execute('SELECT COUNT(*) FROM equipment')
        stats['total'] = cursor.fetchone()[0]

        # Active equipment
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
        stats['active'] = cursor.fetchone()[0]

        # Run to Failure
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Run to Failure'")
        stats['run_to_failure'] = cursor.fetchone()[0]

        # Missing equipment
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Missing'")
        stats['missing'] = cursor.fetchone()[0]

        # Equipment with Monthly PM - return both equipment count and annual workload
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE monthly_pm = TRUE AND status = 'Active'")
        monthly_equipment = cursor.fetchone()[0]
        stats['monthly_pm'] = monthly_equipment
        stats['monthly_pm_annual_workload'] = monthly_equipment * 12

        # Equipment with Annual PM - return both equipment count and annual workload
        cursor.execute("SELECT COUNT(*) FROM equipment WHERE annual_pm = TRUE AND status = 'Active'")
        annual_equipment = cursor.fetchone()[0]
        stats['annual_pm'] = annual_equipment
        stats['annual_pm_annual_workload'] = annual_equipment * 1

        return stats

    def get_equipment_requiring_attention(self) -> Dict[str, List[Dict]]:
        """
        Get equipment requiring attention (overdue PMs, missing equipment, etc.)

        Returns:
            Dictionary with categories of equipment requiring attention
        """
        cursor = self.conn.cursor()

        results = {
            'overdue_monthly': [],
            'overdue_annual': [],
            'missing': [],
            'no_pm_history': []
        }

        # Overdue monthly PMs (more than 35 days)
        cursor.execute('''
            SELECT bfm_equipment_no, description, last_monthly_pm,
                   CURRENT_DATE - last_monthly_pm::date as days_overdue
            FROM equipment
            WHERE monthly_pm = TRUE
            AND status = 'Active'
            AND last_monthly_pm IS NOT NULL
            AND CURRENT_DATE - last_monthly_pm::date > 35
            ORDER BY days_overdue DESC
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            results['overdue_monthly'].append({
                'bfm_no': row[0],
                'description': row[1],
                'last_pm': row[2],
                'days_overdue': row[3]
            })

        # Overdue annual PMs (more than 370 days)
        cursor.execute('''
            SELECT bfm_equipment_no, description, last_annual_pm,
                   CURRENT_DATE - last_annual_pm::date as days_overdue
            FROM equipment
            WHERE annual_pm = TRUE
            AND status = 'Active'
            AND last_annual_pm IS NOT NULL
            AND CURRENT_DATE - last_annual_pm::date > 370
            ORDER BY days_overdue DESC
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            results['overdue_annual'].append({
                'bfm_no': row[0],
                'description': row[1],
                'last_pm': row[2],
                'days_overdue': row[3]
            })

        # Missing equipment
        cursor.execute('''
            SELECT bfm_equipment_no, description, location
            FROM equipment
            WHERE status = 'Missing'
            ORDER BY bfm_equipment_no
        ''')

        for row in cursor.fetchall():
            results['missing'].append({
                'bfm_no': row[0],
                'description': row[1],
                'location': row[2]
            })

        # Equipment with no PM history but requiring PMs
        cursor.execute('''
            SELECT bfm_equipment_no, description, monthly_pm, annual_pm
            FROM equipment
            WHERE status = 'Active'
            AND (monthly_pm = TRUE OR annual_pm = TRUE)
            AND (
                (monthly_pm = TRUE AND (last_monthly_pm IS NULL OR last_monthly_pm = ''))
                OR
                (annual_pm = TRUE AND (last_annual_pm IS NULL OR last_annual_pm = ''))
            )
            ORDER BY bfm_equipment_no
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            results['no_pm_history'].append({
                'bfm_no': row[0],
                'description': row[1],
                'has_monthly': row[2] if row[2] is not None else False,
                'has_annual': row[3] if row[3] is not None else False
            })

        return results

    def validate_bfm_number(self, bfm_no: str) -> bool:
        """
        Validate if BFM number exists in database

        Args:
            bfm_no: BFM equipment number

        Returns:
            True if exists, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            count = cursor.fetchone()[0]
            cursor.close()
            # Commit to end the transaction cleanly
            self.conn.commit()
            return count > 0
        except Exception as e:
            # Rollback on error
            try:
                self.conn.rollback()
            except:
                pass
            raise e

    def add_equipment(self, equipment_data: Dict, user_id: str) -> Tuple[bool, str]:
        """
        Add new equipment to database

        Args:
            equipment_data: Dictionary with equipment details
            user_id: User adding the equipment

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            cursor = self.conn.cursor()

            # Check if BFM already exists
            if self.validate_bfm_number(equipment_data['bfm_no']):
                return False, f"Equipment {equipment_data['bfm_no']} already exists"

            # Insert equipment
            cursor.execute('''
                INSERT INTO equipment (
                    bfm_equipment_no, description, location, monthly_pm, annual_pm, status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                equipment_data['bfm_no'],
                equipment_data.get('description', ''),
                equipment_data.get('location', ''),
                equipment_data.get('has_monthly', False),
                equipment_data.get('has_annual', False),
                equipment_data.get('status', 'Active')
            ))

            # Log audit trail
            cursor.execute('''
                INSERT INTO audit_log (table_name, record_id, action, user_id, new_values, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                'equipment',
                equipment_data['bfm_no'],
                'insert',
                user_id,
                str(equipment_data),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))

            self.conn.commit()
            return True, f"Equipment {equipment_data['bfm_no']} added successfully"
        except Exception as e:
            print(f"Error adding equipment: {e}")
            self.conn.rollback()
            return False, f"Error adding equipment: {str(e)}"

    def delete_equipment(self, bfm_no: str, user_id: str) -> Tuple[bool, str]:
        """
        Delete equipment from database (use with caution)

        Args:
            bfm_no: BFM equipment number
            user_id: User deleting the equipment

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            cursor = self.conn.cursor()

            # Get equipment details for audit
            equipment = self.get_equipment_by_bfm(bfm_no)
            if not equipment:
                return False, f"Equipment {bfm_no} not found"

            # Delete equipment
            cursor.execute('DELETE FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))

            # Log audit trail
            cursor.execute('''
                INSERT INTO audit_log (table_name, record_id, action, user_id, old_values, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                'equipment',
                bfm_no,
                'delete',
                user_id,
                str(equipment),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))

            self.conn.commit()
            return True, f"Equipment {bfm_no} deleted successfully"
        except Exception as e:
            print(f"Error deleting equipment: {e}")
            self.conn.rollback()
            return False, f"Error deleting equipment: {str(e)}"
